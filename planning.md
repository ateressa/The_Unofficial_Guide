# The Unofficial Guide — Planning Doc

Use this file to record your design decisions as you work through the lab.
There are no wrong answers — write enough that you could explain your reasoning to another group.

---
## Architecture

Five-stage RAG pipeline, each stage labeled with the tool/library it uses:

```
┌─────────────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│ 1. DOCUMENT          │   │ 2. CHUNKING      │   │ 3. EMBEDDING +       │
│    INGESTION         │──▶│                  │──▶│    VECTOR STORE      │
│                      │   │ hybrid, per-     │   │                      │
│ Reddit .json (PRAW-  │   │ source splitter: │   │ all-MiniLM-L6-v2     │
│ style .json trick),  │   │ • RMP: 1 review  │   │ (sentence-           │
│ RMP .txt, PDF syllabi│   │ • Reddit: 1 cmnt │   │  transformers)       │
│                      │   │ • PDF: recursive │   │        │             │
│ custom Python        │   │   char split     │   │        ▼             │
│ (ingest.py) +        │   │                  │   │ ChromaDB             │
│ pdfplumber           │   │ custom Python    │   │ (cosine, persistent) │
└─────────────────────┘   └──────────────────┘   └──────────┬───────────┘
                                                             │
                    ┌────────────────────────────────────────┘
                    ▼
        ┌──────────────────────┐        ┌──────────────────────┐
        │ 4. RETRIEVAL         │        │ 5. GENERATION        │
        │                      │───────▶│                      │
        │ hybrid: semantic     │ top-k  │ Groq                 │
        │ (ChromaDB) + keyword │ chunks │ Llama-3.3-70b        │
        │ (BM25), rank fusion  │ (k=5)  │ (generator.py)       │
        │ top-k = 5            │        │                      │
        │ (retriever.py)       │        │ grounded answer +    │
        └──────────────────────┘        │ source attribution   │
                    ▲                    └──────────┬───────────┘
                    │                               │
              user query                       answer to user
```

**Flow:** raw documents are ingested and parsed → split into chunks by a
per-source splitter → embedded with all-MiniLM-L6-v2 and stored in ChromaDB →
a user query retrieves the top-k chunks via hybrid (semantic + keyword) search
→ Groq Llama-3.3-70b generates a grounded answer from those chunks. The UI layer
is Gradio (`app.py`). *(Claude is a development coworker, not a runtime stage —
see AI Tool Plan.)*

---
## Domain
**Student experiences with the courses required for the ASU Computer Science
(BS) degree** — the CSE core (e.g. CSE 110/205/230/240/310) plus the required
math, stats, and logic courses (MAT 265, CSE 259, IEE 380, etc.). The focus is
the *course*: what it's actually like to take — workload, exam difficulty,
projects, whether it's a weed-out, and which professor to pick for it.

Why this knowledge is valuable and hard to find officially:
- **Official channels describe, they don't evaluate.** The ASU catalog and
  degree checksheet tell you a course's topics, credits, and prerequisites —
  but never that CSE 240 is a workload spike, that a given professor curves, or
  that one section is far harder than another.
- **The real answers are scattered and ephemeral.** This knowledge lives in
  r/ASU threads, Rate My Professors reviews, and word-of-mouth. It's spread
  across dozens of posts, written by anonymous students, and can be edited or
  deleted at any time — there's no single searchable place that aggregates it.
- **It's exactly the question students ask before registering** ("is this prof
  worth it / how hard is this class / will it wreck my semester"), and getting
  it wrong is expensive in GPA and time. A RAG system that synthesizes the
  crowd's experience into a direct answer is genuinely useful.

## Documents
The corpus is collected by hand and saved offline (so it's reproducible and
can't change before evaluation), organized by source type under `data/`. Three
source types give three complementary perspectives:

**1. Reddit — r/ASU threads (`data/reddit/`, 15 files, ~200 posts+comments)**
Saved via the `.json` trick (append `.json` to the thread URL) so we keep
structured data plus metadata (author, score, date). Conversational, candid,
course-level experiences:
- CSE 240 — 5 threads (`reddit_asu_cse240.json` … `_e.json`)
- CSE 310 — 5 threads (`reddit_asu_cse310.json` … `_e.json`)
- CSE 110, CSE 205, CSE 230 — 1 thread each
- MAT 265 — 1 thread (`mat_265_caclulus_for_engineers.json`)
- Cross-course professor reviews — `reddit_asu_cs_prof_reviews.json`

**2. Rate My Professors (`data/rmp/`, 12 files, one per professor)**
Saved as `.txt`. Short, opinion-dense reviews, each carrying structured
metadata (Quality, Difficulty, course taken, date, grade, "would take again",
tags). Answers "which professor is clearest / worth retaking":
- CSE: Richa, Miller, Nelson, Bryan, Ahmad, Davulcu, Yau, Gordon
- MAT 265: Yu, Rody, Mohacsy
- IEE 380: Chattin

**3. Course syllabi (`data/pdf/`, 5 PDFs)**
Native PDFs of official Spring 2025 syllabi for CSE 110, 205, 230, 240, and
310. These supply the *ground-truth* structure of each course — grading
breakdown, exam/project schedule, policies — to balance the subjective Reddit
and RMP reviews with authoritative facts.

These three sources cover different perspectives on the same questions: Reddit =
candid crowd experience, RMP = professor-specific reviews, syllabi = official
course structure. Together they let the system answer both "how hard is it /
which prof" (opinion) and "what's the grading breakdown" (fact).

*Note on coverage: the corpus is intentionally deepest on CSE 240 and CSE 310
(the courses we had time to collect thoroughly) and thinner on the math/stats
requirements; see Anticipated Challenges.*

## Chunking Strategy
We use a **hybrid, structure-aware strategy** — a different splitter per source
type — rather than one global chunk size. Our documents are already segmented
into natural units (a single review, a single comment), so the best chunk
boundary is the one the source already gives us. A single fixed-character
window would cut across those units and, on opinion data, that's the worst
failure mode: it merges two students' opposing verdicts into one chunk, or
separates a review's conclusion ("worth it") from its reasoning.

For each source we also **extract the structured fields as chunk metadata**
(not embedded text), so the embedding sees only clean prose and we can later
filter by recency/grade. Every chunk additionally stores `source`, the
course/professor, and the source URL or filename for attribution.

**Contextual headers.** We prepend a short identifier line to each chunk's
*embedded* text — e.g. `Rate My Professors review — Connor Nelson:` or
`CSE 240 — Reddit r/ASU:`. Without this, pure semantic search can't find a
review of "Connor Nelson" whose body never says "Nelson" (the name lives only
in metadata, which isn't embedded). Embedding the identifier fixed this in
testing: a "Connor Nelson" query went from 0/3 relevant results to 3/3. This is
a deliberate refinement of "embed clean prose only," and it stacks with the
planned keyword search.

**1. RMP reviews → record-based split (one review = one chunk).**
Each file is a sequence of self-contained review records with a fixed shape
(`Quality → Difficulty → course → date → For Credit/Attendance/Would Take
Again/Grade → review text → tags`). We split on that repeating record boundary
so each chunk is exactly one student's review.
- Chunk = one review (~300–700 chars). No overlap — records are independent, so
  there's no fact spanning a boundary to preserve.
- Metadata extracted: `quality`, `difficulty`, `course`, `date`, `grade`,
  `would_take_again`. Embedded text = the free-form review sentence(s) only; the
  UI-chrome lines (`Thumbs up / 0`, "Similar Professors", etc.) are stripped.

**2. Reddit threads → per-comment split (one comment/post = one chunk).**
Parsed from the `.json` structure: the post selftext is one chunk and each
comment is its own chunk, so a chunk never blends two authors. Observed comment
lengths in our threads run 12–622 chars (median ~112), so most comments fit in
a single chunk cleanly.
- Chunk = one post or one comment. Recursive-character fallback (split on
  `\n\n` → sentence, ~600-char cap, ~80 overlap) **only** for the rare long
  comment that exceeds the cap.
- `min_length = 40` chars to drop low-signal noise (`"lol same"`, `"this"`).
- Metadata extracted: `author`, `score`, `created_utc` (date), `thread_title`.

**3. PDF syllabi → recursive character split.**
These are the only long, continuous documents (grading tables, weekly schedule,
policies) with no repeating record to split on, so we use a recursive splitter:
try `\n\n` (sections/paragraphs) first, then `\n`, then sentences, falling back
to a hard character cap.
- Target ~800–1000 chars, **~120-char overlap**. Larger than the review chunks
  because syllabus facts (e.g. a grading-weight sentence) need surrounding
  context to be meaningful, and overlap keeps a policy that straddles a
  paragraph break retrievable from either side.

**Why these sizes / how we'll know they're wrong.**
- *Too small* (e.g. splitting a review by sentence): retrieval returns a tag
  like "Tough grader" with no context, and the LLM can't tell which course or
  whether it's positive overall.
- *Too large* (e.g. a whole RMP file as one chunk): a query about one professor
  pulls in 43 mixed reviews, diluting the signal so the most relevant verdict
  doesn't rank.
- We'll know chunking is off if eval queries return the right *document* but the
  wrong *passage* (too large), or fragments that read as non-sequiturs (too
  small).

## Retrieval Approach
**Embedding model: `all-MiniLM-L6-v2` via sentence-transformers** (384-dim).
It's a strong fit for *this* corpus: our chunks are short (single reviews and
comments, well under the model's 256-token limit), so its short context window
is not a constraint, and it's fast and lightweight enough to embed the whole
corpus and run queries locally with no API cost. Stored and searched in ChromaDB
with cosine similarity.

**Retrieval mode: hybrid (semantic + keyword).** We combine dense semantic
search with sparse keyword search rather than relying on embeddings alone,
because our queries mix two very different needs:
- *Exact identifiers* — course codes and professor names ("CSE 240", "Richa",
  "MAT 265") are precise tokens. Embeddings blur them (CSE 240 and CSE 340 are
  near-neighbors in vector space but are different courses), so a purely
  semantic search can pull reviews for the wrong course. A keyword match pins
  the exact code/name.
- *Paraphrased opinions* — "is it a weed-out," "tough grader," "curve saved me"
  share no keywords with each other; only semantic search clusters them.

**Implemented:** both retrievers run over the same chunks — semantic via
ChromaDB (MiniLM embeddings) and keyword via BM25 (`rank-bm25`) — and the two
ranked lists are **fused with reciprocal-rank fusion** (`retriever.py`). This
way an exact "CSE 240" match and a semantically-relevant "half the class
dropped" comment can both surface for one query. In testing, adding BM25 took
professor-name queries (e.g. "Connor Nelson") to 4/4 relevant results.

**Metadata filtering (course auto-filter).** When a query names exactly one
course code, retrieval auto-filters to `where={"course": "<code>"}` so
"How hard is CSE 240?" returns only CSE 240 chunks instead of pulling in
similarly-worded CSE 110 comments. Multi-course queries ("CSE 240 vs CSE 230")
skip the filter, and an empty filtered result falls back to unfiltered search.

**Top-k: start at 5.** Because each chunk is one student's review/comment,
retrieving 5 chunks means the LLM sees ~5 independent opinions — enough to
synthesize a consensus ("most students say…") rather than parroting a single
voice. This is a deliberate bump from the starter's `N_RESULTS = 3`, which is
too few for opinion-aggregation questions. We'll treat k as a tuning knob driven
by the Evaluation Plan:
- *Too few* (k=1–3): the answer hinges on one or two reviews and misses the
  spread of opinion; a single outlier ("this prof is great!") can dominate.
- *Too many* (k=10+): off-topic or weakly-related chunks dilute the context,
  the LLM hedges or drifts, and answers get slower.
- Plan: start at k=5, raise toward ~8 if answers feel thin or one-sided, lower
  if eval shows irrelevant chunks creeping in.

**Why semantic search works without shared keywords.** The embedding maps text
to a vector by *meaning*, not exact words, so a query like "is CSE 240 a
weed-out?" lands near a comment that says "half the class dropped after the
first exam" even though they share no keywords. This matters a lot for our data:
students phrase the same complaint a hundred different ways ("brutal," "curve
saved me," "don't take it with…"), and semantic search clusters those together
where literal keyword matching would miss them.

**If cost weren't a constraint** we'd weigh a larger model (e.g. `bge-large` or
an OpenAI `text-embedding-3` model). The trade-offs for *our* domain:
- *Domain/nuance accuracy* — the main potential win: bigger models capture the
  subtle, slangy, sarcastic tone of student reviews better, improving ranking on
  ambiguous queries. This is the only axis where we'd likely see real gains.
- *Context length* — **not** a deciding factor here; our chunks are short, so a
  longer context window would sit mostly unused.
- *Multilingual* — irrelevant; the corpus is English-only.
- *Latency / cost* — the cost of upgrading: larger local models are slower and
  heavier, and API-based embeddings add per-call latency, network dependence,
  and spend. For a small, short-text corpus, MiniLM's speed-to-quality ratio is
  hard to beat, which is why we keep it.

## Evaluation Plan
1. **Is Connor Nelson worth taking?** → No / polarizing: 1.9/5, only 21% would
   take again (73 ratings).
2. **What do students think of Andrea Richa?** → Well-liked: 4.0/5, 86% would
   take again; theoretical but valuable, clear and caring.
3. **How hard is CSE 240?** → Hard / heavy workload; commonly called a
   weed-out, low-level C, tough exams.
4. **What is CSE 310 about and is it difficult?** → Data structures &
   algorithms; challenging, significant workload.
5. **How is Linda Chattin for IEE 380 (stats)?** → Well-regarded: 4.2/5, 76%
   would take again (298 ratings).

**Results (5/5 grounded & correct verdicts):** Each question returned a
source-attributed answer matching the expected verdict — Nelson "not worth
taking" (reviews all 1.0/5), Richa praised but course is hard, CSE 240 heavy
workload, CSE 310 = data structures/algorithms in C++ and challenging, Chattin
well-regarded. *Known limitation:* answers synthesize the retrieved top-k, not
the aggregate, so the system can't cite headline stats like "21% would take
again" — those live in the RMP file header, which the parser skips. Fixable by
ingesting the header summary as its own chunk.

## Anticipated Challenges
- **Noisy / inconsistent documents** — manual collection pulled in UI chrome,
  off-topic chatter, and varied formatting; risks junk chunks if not cleaned.
- **Skewed coverage** — corpus is deep on CSE 240/310, thin on math/stats, so
  those queries may retrieve weak or no results.
- **Wrong-course retrieval** — similar course codes/prof names can cross-match
  (mitigated, and confirmed in testing, by hybrid keyword search + the course
  auto-filter).

## AI Tool Plan

ingestion/chunking = custom Python (`ingest.py`); embedding + search =
sentence-transformers + ChromaDB (`retriever.py`); generation = Groq
Llama-3.3-70b (`generator.py`). Claude never runs at query time — it only helps
me write and debug that code:
- **Ingestion/chunking:** I give Claude the Documents + Chunking sections and
  ask it to help me write the parsers/splitters in `ingest.py`.
- **Retrieval:** I give it the Retrieval Approach section and ask for help
  implementing hybrid search + rank fusion in `retriever.py`.
- **Debugging/eval:** I ask it to help trace failures and compare system output
  against my 5 evaluation answers.



