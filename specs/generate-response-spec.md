# Spec: `generate_response()`

**File:** `generator.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user query and a list of retrieved rule chunks, generate a response that directly answers the question using only the retrieved text as context. The response must be grounded — it should not draw on the model's general knowledge of board games, only on what was retrieved.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's original question |
| `retrieved_chunks` | `list[dict]` | Ranked list of chunks from `retrieve()`, each with `"text"`, `"game"`, and `"distance"` |

**Output:** `str`

A plain string containing the response to show the user. The response should:
- Answer the question using only the retrieved rule text
- Identify which game the answer comes from
- Acknowledge clearly when the answer is not found in the loaded rules

Returns a fallback string (not an error) when `retrieved_chunks` is empty.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Context formatting

*How will you format the retrieved chunks before passing them to the LLM? Describe the structure — not the code. Consider: will you label chunks by game? Include distance scores? Separate chunks with delimiters?*

```
Each retrieved chunk is formatted as a labeled block using all three fields from
the retriever output (text, game, distance):

    Chunk 1 | Game: Catan | Distance: 0.18
    Settlements cost 1 Brick + 1 Lumber + 1 Grain + 1 Wool...

    ---

    Chunk 2 | Game: Risk | Distance: 0.64
    Players take turns placing armies on territories...

    ---

    Chunk 3 | Game: Monopoly | Distance: 0.71
    When a player lands on an owned property...

Rationale:
- Game label on every chunk so the model can attribute answers correctly and
  skip off-topic chunks when the query targets a specific game.
- Distance score included for console debugging and to give the model a signal
  about which chunks are most relevant (lower = more similar to the query).
- "---" delimiter between chunks because rule text is plain prose — without a
  separator, multiple 300-char chunks run together and provenance is lost.
- No distance filtering at this stage; all retrieved chunks are passed in.
  Thresholds will be determined after observing real console output.
```

---

### System prompt — grounding instruction

*Write the exact system prompt instruction you will use to prevent the model from answering beyond the retrieved text. This is the most important design decision in this function.*

```
You are a board game rules reference. The retrieved rule excerpts below are your only permitted source of information.

Do not use your training knowledge of board games for any purpose: not to fill gaps in the retrieved text,
not to add context, not to correct the excerpts, and not to infer answers from partial information.
Answer only what the excerpts explicitly state. If they do not contain a clear answer, say so.
```

---

### System prompt — citation instruction

*Write the exact instruction you will use to tell the model to identify which game its answer comes from.*

```
When you answer, state which game each answer comes from.
If the question names a specific game, only use chunks from that game.
If no game is specified, answer for every game represented in the retrieved chunks, labeled by game name.
```

---

### Fallback behavior

*What should the response say when the answer isn't found in the loaded rule books? Write the exact fallback message.*

```
"I couldn't find anything relevant in the loaded rule books.
Try rephrasing your question — or check that your ingestion pipeline is working."

This is returned directly (not via the LLM) when retrieved_chunks is empty.
```

---

### Handling low-relevance chunks

*`retrieved_chunks` may include chunks with high distance scores (weak relevance). Will you filter these out before building context, pass them all in, or handle them another way? What are the tradeoffs?*

```
Pass all retrieved chunks in without filtering. Distance scores are included in the
formatted context so they are visible in console output during testing.

Rationale: filtering thresholds are unknown until real queries are observed. Filtering
too early risks discarding the only relevant chunk. Thresholds will be set after
testing with real queries.
```

---

### Message structure

*Describe how you will structure the messages list for the API call — what goes in the system message vs. the user message?*

```
System message: grounding instruction + citation instruction (_SYSTEM_PROMPT)

User message:
    Retrieved rule excerpts:

    Chunk 1 | Game: Catan | Distance: 0.18
    <chunk text>

    ---

    Chunk 2 | Game: Risk | Distance: 0.64
    <chunk text>

    Question: <user query>

The system message stays fixed per call. All variable content (chunks + query)
goes in the user message. No conversation history is passed — each call is stateless.
```

---

## Implementation Notes

**Test query and response:**

```
Query: What happens if you roll a 7 in Catan?

Response: In Catan, when a 7 is rolled, no resources are produced, and every player
with more than 7 resource cards in hand must discard half (rounded down). The player
who rolled then moves the robber to any terrain hex and steals one resource.

Correctly grounded? No
Cited the right game? Yes
```

**What went wrong:**

```
The grounding failed in two ways:

1. The relevant chunk was never retrieved. The "ROLLING A 7" section of the rulebook
   (the direct answer) was not in the top 3 results. Instead, retrieve() returned a
   chunk about the robber blocking production, the overview paragraph, and an Uno chunk.
   The model had no retrieved text to ground on.

2. The model answered from training knowledge anyway. Despite the grounding instruction,
   llama-3.3-70b knows Catan well and produced a confident answer without the retrieved
   text. The instruction alone is not sufficient when the model has strong prior knowledge.

3. The answer is slightly incomplete. The model said "steals one resource" but the
   rulebook specifies "steals one random resource card from a player with a settlement
   or city adjacent to that hex." The adjacency constraint — which determines whether
   you can steal at all — was dropped.
```

**Test query 2 and response:**

```
Query: How do you win? (no game specified)

Response:
- Monopoly: The last player remaining after all others have gone bankrupt wins.
- Risk: The first player to complete their secret mission wins. In classic play,
  the last player to hold any territory wins.
- Ticket to Ride: The player who completed more destination tickets wins in case
  of a tie, but the general winning condition is not explicitly stated in the
  provided excerpt.

Correctly grounded? Yes
Cited the right game? Yes
```

**What went right (test 2):**

```
1. Multi-game behavior worked. With no game specified, the model answered for all
   three retrieved games and labeled each by name.

2. Grounding held on Ticket to Ride. The retrieved chunk contained only the
   tiebreaker sentence — the main win condition was cut off by the 300-char chunk
   boundary. The model correctly flagged the gap ("not explicitly stated in the
   provided excerpt") instead of filling it in from training data.

3. Monopoly and Risk answers were verbatim matches to the rulebook.
```

**Retrieval tuning experiment:**

```
Hypothesis: the "ROLLING A 7" chunk was being split at the 300-char boundary,
causing neither half to score well in semantic search. Tested three configurations:

  chunk_size=300, N_RESULTS=3  → 149 chunks | best Catan dist: 0.471 | not retrieved
  chunk_size=500, N_RESULTS=5  →  85 chunks | best Catan dist: 0.484 | not retrieved
  chunk_size=400, N_RESULTS=5  → 108 chunks | best Catan dist: 0.520 | not retrieved

Conclusion: chunk size and result count are not the root cause. The "ROLLING A 7"
chunk did not appear in the top 5 in any configuration. chunk_size=300 actually
produced the tightest distance scores. The problem is the embedding model —
all-MiniLM-L6-v2 does not reliably map natural-language questions to rule-text
section headers. Reverted to chunk_size=300, N_RESULTS=3.
```

**One thing you changed from your original spec after seeing the actual output:**

```
Retrieval quality is the deciding variable, not the prompt. When the right chunk
was retrieved (test 2, multi-game), grounding worked correctly. When it wasn't
(test 1, Catan rolling-a-7), the model fell back to training knowledge despite
the grounding instruction. Tuning chunk_size and N_RESULTS did not fix the
retrieval failure — the ceiling is the embedding model itself.
```
