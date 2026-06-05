# Spec: `retrieve()`

**File:** `retriever.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user's natural language query, find the most relevant chunks from the vector store using semantic similarity search. Return them ranked by relevance so that `generate_response()` can use them as context.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's natural language question |
| `n_results` | `int` | Maximum number of chunks to return (default: `N_RESULTS` from `config.py`) |

**Output:** `list[dict]`

Each dict in the returned list must contain exactly these keys:

| Key | Type | Description |
|-----|------|-------------|
| `"text"` | `str` | The chunk text |
| `"game"` | `str` | The game name this chunk came from |
| `"distance"` | `float` | Cosine distance score — lower means more similar to the query |

Results should be ordered from most to least relevant (lowest to highest distance). Returns an empty list `[]` if the collection contains no documents.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Query approach

*Describe how you will use `_collection.query()` to find relevant chunks. What arguments will you pass, and why?*

```
To run a semantic search, _collection.query() takes:
      - query_texts : a list containing your query string
      - n_results   : how many results to return
      - include     : what to return — use ["documents", "metadatas", "distances"]
Why? Passing query_texts = [query] lets Chroma compute the query embedding with the collection's embedding function. n_results caps the returned candidates for efficiency and downstream context size. include = ["documents", "metadatas", "distances"] returns chunk text, metadata, and cosine distances.  
```

---

### Return structure

*Sketch out what one item in your return list looks like as a concrete example. Where does each field come from in the query results?*

```
{
      "text": query_results["documents"][0][i],
      "game": query_results["metadatas"][0][i]["game"],
      "distance": float(query_results["distances"][0][i])
}

For example, if the first returned chunk is about Uno, one item could look like:

{
      "text": "When a player has one card left, they must say 'Uno' before the next player takes their turn.",
      "game": "uno",
      "distance": 0.18
}

The "text" comes from the documents list, the "game" comes from the chunk metadata, and the "distance" comes from Chroma's distance scores for that match.
```

---

### Handling the nested result structure

*`_collection.query()` returns nested lists. Describe what index you need to access to get the actual list of results for a single query, and why the nesting exists.*

```
Use index [0] to get the results for the single query, because Chroma returns one outer list per query in `query_texts`. Since `retrieve()` sends only one query string, the actual documents, metadatas, and distances are all inside the first element of each returned list.
```

---

### Relevance threshold

*Will you filter out results above a certain distance score, or return all `n_results` regardless of how relevant they are? What are the tradeoffs of each approach?*

```
Return the top `n_results` without applying an extra distance cutoff. That keeps the behavior predictable and lets the caller decide how much context to use. The tradeoff is that some weak matches may still appear, but ranking still puts the best chunks first and avoids accidentally dropping useful edge-case matches.
```

---

### Edge cases

*How does your implementation behave when: (a) the collection is empty, (b) the query matches no chunks well, (c) the query matches chunks from multiple games?*

```
If the collection is empty, return `[]` immediately. If the query does not match anything especially well, still return the best `n_results` chunks so the caller can inspect the strongest available context. If the query matches chunks from multiple games, return the highest-ranked results across all games and include each chunk's `game` metadata so the caller can tell where each one came from.
```

---

## Implementation Notes

*Fill this in after implementing, before moving to Milestone 3.*

**Test query and top result returned:**

```
Query: [your test query]
Top result game: [game name]
Distance score: [score]
Does it make sense? [yes / no / explain]
```

**One thing about the query results that surprised you:**

```
[your answer here]
```
