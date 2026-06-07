# 🎓 The Unofficial Guide

> Straight talk on ASU Computer Science courses & professors — from real student reviews, not the course catalog.

The Unofficial Guide answers natural-language questions about the courses ASU CS
(BS) majors actually have to take — *how hard is it, who should I take it with,
is it a weed-out?* — using a Retrieval-Augmented Generation (RAG) pipeline over
**real student experiences**: r/ASU threads, Rate My Professors reviews, and
official course syllabi. Answers are **grounded in the collected sources only**;
if the sources don't cover something, it says so instead of guessing.

> 📄 The full design rationale (domain motivation, chunking trade-offs, retrieval
> design, evaluation plan) lives in [`planning.md`](planning.md), written before
> implementation. This README is the evidence/results document.

---

## How it works

A five-stage RAG pipeline:

```
Documents ──► Chunking ──► Embedding + Vector Store ──► Retrieval ──► Generation
 reddit/rmp/   per-source    all-MiniLM-L6-v2            hybrid:        Groq
 pdf (custom   structure-    + ChromaDB (cosine)         semantic +     Llama-3.3-70b
 Python)       aware                                     BM25 (RRF)
```

| Stage | File | What it does |
|-------|------|--------------|
| Ingestion + chunking | [`ingest.py`](ingest.py) | Per-source loaders → structure-aware chunks |
| Embedding + retrieval | [`retriever.py`](retriever.py) | Embed/store in ChromaDB + hybrid (semantic+BM25) search |
| Generation | [`generator.py`](generator.py) | Grounding prompt + multi-turn query rewrite (Groq) |
| UI | [`app.py`](app.py) | Gradio chat interface + startup ingestion |

---

## Domain and Document Sources

**Domain:** student experiences with the courses required for the **ASU Computer
Science (BS)** degree — the CSE core (CSE 110 / 205 / 230 / 240 / 310) plus the
required math/stats/logic courses (MAT 265, CSE 259, IEE 380). The focus is the
*course*: workload, exam difficulty, whether it's a weed-out, and which professor
to pick. This knowledge is valuable because official channels *describe* courses
(topics, credits) but never *evaluate* them, and the real answers are scattered
across ephemeral, anonymous posts. (Full motivation in [`planning.md`](planning.md).)

The corpus is **collected by hand and saved offline** so it's reproducible and
can't change before evaluation. Real ingestion run: **420 documents → 611 chunks**
(`reddit`: 171, `rmp`: 258 reviews, `pdf`: 5; 14 duplicate docs dropped).

| Source | What | Format | Count |
|--------|------|--------|-------|
| **r/ASU threads** | Candid, course-level student experiences | `.json` (post + comments) | 15 files |
| **Rate My Professors** | Professor-specific reviews with ratings | `.txt`, one per professor | 12 files |
| **Course syllabi** | Official course structure (grading, policies) | `.pdf` | 5 files |

**Specific sources (names + URLs):**

- **Reddit / r/ASU** (saved via the `.json` trick — append `.json` to a thread URL).
  Example threads in the corpus:
  - [Probably going to fail CSE240. Should I retake it before CSE230?](https://reddit.com/r/ASU/comments/116hszf/probably_going_to_fail_cse240_should_i_retake_it/)
  - [Any tips for CSE 240 with Chen?](https://reddit.com/r/ASU/comments/s44lxh/any_tips_for_cse_240_with_chen/)
  - [Taking CSE 205 Spring 2024](https://reddit.com/r/ASU/comments/184x00n/taking_cse_205_spring_2024/)
  - [CSE 310 with yiran luo](https://reddit.com/r/ASU/comments/1epk4xk/cse_310_with_yiran_luo/)
  - [CSE 310 prep](https://reddit.com/r/ASU/comments/18p2w61/cse_310_prep/)
- **Rate My Professors** — `ratemyprofessors.com`, ASU professor pages. Reviews
  collected for: Richa, Miller, Nelson, Bryan, Ahmad, Davulcu, Yau, Gordon (CSE);
  Yu, Rody, Mohacsy (MAT 265); Chattin (IEE 380). Files: `data/rmp/rmp_<prof>_<dept>.txt`.
- **Course syllabi** — official ASU Spring 2025 syllabi (CSE 110, 205, 230, 240, 310).
  Files: `data/pdf/asu_cse<NNN>_syllabus_sp25.pdf`.

See [`data/README.md`](data/README.md) for collection notes and naming conventions.

---

## Chunking Strategy

We use a **hybrid, structure-aware strategy** — a different splitter per source
type — rather than one global chunk size, because each source is already
segmented into natural units. A fixed-character window would cut across those
units; on opinion data that's the worst failure mode (merging two students'
opposing verdicts into one chunk, or splitting a review's conclusion from its
reasoning).

| Source | Boundary | Size / Overlap | Why |
|--------|----------|----------------|-----|
| **RMP review** | one review = one chunk | ~300–700 chars, **no overlap** | Records are independent; no fact spans a boundary |
| **Reddit** | one post / one comment = one chunk | recursive fallback at ~600 chars, **~80 overlap**, only for rare long comments; `min_length=40` drops noise | A chunk never blends two authors |
| **PDF syllabus** | recursive char split (`\n\n` → `\n` → sentence) | ~**900 chars / ~120 overlap** | Long continuous docs; syllabus facts need surrounding context |

Two refinements (both in [`ingest.py`](ingest.py)):

- **Metadata extraction.** Structured fields (`quality`, `difficulty`, `grade`,
  `author`, `score`, `date`, `course`) are pulled into chunk *metadata*, not
  embedded text — so embeddings see clean prose and we can filter/attribute later.
- **Contextual headers.** A short identifier line is prepended to each chunk's
  *embedded* text (e.g. `Rate My Professors review — Connor Nelson:`). Without it,
  semantic search can't find a review of "Connor Nelson" whose body never says
  "Nelson" (the name lives only in metadata). In testing this took a "Connor
  Nelson" query from 0/3 to 3/3 relevant results.

### Sample chunks (5, labeled with source document)

**Sample 1 — `rmp_nelson_cse.txt`** (RMP; quality 5.0/5, difficulty 3.0/5, grade A+, would-take-again: Yes)
```
Rate My Professors review — Connor Nelson:
This class is hard, and is hated by the student population for one reason: you
have to critically think. Yeah you struggle, but isn't that the point of
learning at higher education? Dr. Nelsons class exemplifies this... the reward
of the knowledge is so much more than cost for struggle. Food for thought.
```

**Sample 2 — `rmp_richa_cse.txt`** (RMP; CSE 450, quality 5.0/5, difficulty 4.0/5, grade A, Oct 14th 2025)
```
Rate My Professors review — Andrea Richa, CSE 450:
She is a fantastic professor. This class is purely theoretical (there are no
coding assignments), but you learn a lot of extremely valuable material that
will make you better at algorithms (including leetcode). This is definitely not
an easy class, but doable if you put consistent effort in. Highly recommended.
```

**Sample 3 — Reddit thread `116hszf` (CSE 240)** (comment by u/XChromaX, score 29, 2023-02-19)
```
CSE 240 — Reddit r/ASU:
It really depends who teaches 230. Do not take 230 with indela. I know C/C++ is
hard but it definitely gets harder in CSE 310. I didn't really use pointers
until I watched a couple of youtube videos about it. My number 1 tip for you is
to watch youtubers like codebeauty... CS professors at ASU are basically
glorified assignment givers.
```

**Sample 4 — `asu_cse205_syllabus_sp25.pdf`** (PDF syllabus, CSE 205)
```
CSE 205 course syllabus:
CSE205 – Object Oriented Programming & Data Structures ... Catalog Course
Description: Problem solving by programming with an object oriented programming
language. Introduction to data structures... Required Textbook: CSE 205 ...
zyBook. Expectations: CSE 205 is an exceptionally rigorous and challenging
course. ... you should plan to spend at least 10 hours per week working.
```

**Sample 5 — Reddit thread `1epk4xk` (CSE 310)** (comment by u/iXplos, score 2, 2024-08-14)
```
CSE 310 — Reddit r/ASU:
I took him last semester and he was good. most of the exam questions come from
recitations, and the curve was pretty generous too. the projects aren't too bad
either, but just make sure to not wait until the last day to start. he also
allows a cheat sheet for exams which is really nice. overall really good
professor I would say
```

---

## Embedding Model

**`all-MiniLM-L6-v2`** via `sentence-transformers` (384-dim), stored/searched in
ChromaDB with cosine similarity. It's a strong fit here: our chunks are short
(single reviews/comments, well under its 256-token limit), and it's fast and
light enough to embed the whole corpus and run queries locally with no API cost.

**Production trade-off reflection.** If this were a production deployment and cost
weren't a constraint, the axes I'd weigh against a larger model (`bge-large`,
OpenAI `text-embedding-3`):

- **Domain/nuance accuracy — the main potential win.** Bigger models capture the
  slangy, sarcastic tone of student reviews better, which would improve ranking on
  ambiguous queries. This is the only axis where I'd expect a real gain for us.
- **Context length — not a deciding factor.** Our chunks are short, so a longer
  context window would sit mostly unused.
- **Multilingual — irrelevant.** The corpus is English-only.
- **Latency / cost / dependency — the cost of upgrading.** Larger local models are
  slower and heavier; API embeddings add per-call latency, network dependence, and
  spend, plus a privacy consideration (sending student text to a third party). For
  a small, short-text corpus, MiniLM's speed-to-quality ratio is hard to beat.

A production system would also want **versioned, reproducible embeddings** (pin the
model version; re-embedding the corpus on a model change is a migration, not a
config tweak) and a periodic **re-ingestion job** as new reviews appear.

---

## Retrieval

**Mode: hybrid (semantic + keyword).** Dense semantic search (ChromaDB/MiniLM)
catches paraphrased opinions; sparse BM25 (`rank-bm25`) pins exact course codes and
professor names. The two ranked lists are fused with **Reciprocal Rank Fusion (RRF)**
([`retriever.py`](retriever.py)). Embeddings blur identifiers (CSE 240 vs CSE 340 are
near-neighbors), so semantic-only can pull the wrong course; BM25 pins the exact token.

**Course auto-filter.** When a query names exactly one course code, retrieval
auto-filters to `where={"course": "<code>"}`, so "How hard is CSE 240?" returns only
CSE 240 chunks. Multi-course queries skip the filter; an empty filtered result falls
back to unfiltered search.

**Top-k = 5.** Each chunk is one student's review/comment, so k=5 gives the LLM ~5
independent opinions — enough to synthesize a consensus rather than parrot one voice
(a deliberate bump from the starter's `N_RESULTS = 3`).

### Retrieval test results (3 queries, real output)

**Query 1 — "How hard is CSE 240?"** → auto-filtered to CSE 240; top 5 chunks:

| # | Source | Doc | Excerpt |
|---|--------|-----|---------|
| 1 | reddit | thread `s44lxh` | "I didn't think it was that bad. He has good assignments… tests were hard (as in fast) but open note…" |
| 2 | reddit | thread `116hszf` | "This is if you are ser of course, not cse" |
| 3 | reddit | thread `116hszf` | "It really depends who teaches 230… C/C++ is hard but it gets harder in CSE 310…" |
| 4 | reddit | thread `116hszf` | "I would retake 240 before doing 230… major projects that involve pointer manipulation…" |
| 5 | reddit | thread `s44lxh` | "Keep all your quizzes for the open note tests… he puts so many questions in such a short time…" |

*Why these are relevant:* the course auto-filter kept every chunk on CSE 240
(no cross-course bleed), and chunks 1, 4, and 5 directly speak to difficulty
(test format, workload, pointer-heavy projects). Chunk 2 ("This is if you are
ser of course, not cse") is a genuine miss — a low-signal fragment that slipped
the `min_length` filter (see *Failure Case*).

**Query 2 — "Is Connor Nelson worth taking?"** → top 5 chunks all from `rmp_nelson_cse.txt`:

| # | Source | Doc | Excerpt |
|---|--------|-----|---------|
| 1 | rmp | rmp_nelson_cse.txt | "This class was super wack" |
| 2 | rmp | rmp_nelson_cse.txt | "no NOT take this class unless you wanna hear about this dudes website" |
| 3 | rmp | rmp_nelson_cse.txt | "Teaches nothing, expects everything." |
| 4 | rmp | rmp_nelson_cse.txt | "i bet they won't even learn anything and only make the class harder…" |
| 5 | rmp | rmp_nelson_cse.txt | "Easily hardest course ever taken. The workload will be a full time job plus overtime…" |

*Why these are relevant:* the BM25 half of the hybrid search pinned the exact
name "Connor Nelson," so all five chunks are Nelson reviews (not semantically
similar reviews of *other* professors) — exactly the case pure semantic search
fails. Each excerpt is an opinion on whether he's worth taking, which is the
question asked.

**Query 3 — "What is the grading breakdown for CSE 205?"** → auto-filtered to CSE
205; top 5 chunks mix `asu_cse205_syllabus_sp25.pdf` (4 chunks: dropped-quiz
policy, coding-assignment rules, grade-appeal window, help resources) and one
r/ASU comment. The syllabus chunks are the authoritative source for grading
mechanics, correctly out-ranking the subjective Reddit comment.

---

## Grounded Generation

Grounding is enforced by **pipeline structure + prompt design** (both in
[`generator.py`](generator.py)):

1. **Structural:** the LLM is only ever given the retrieved chunks for that query
   — it has no other corpus access. If retrieval returns nothing, generation is
   short-circuited *before* the LLM is called and a fixed refusal is returned
   ([`generator.py:134`](generator.py#L134)).
2. **Prompt rules** (system prompt, [`generator.py:25`](generator.py#L25)):
   - Use **only** the provided excerpts; never use prior knowledge; never invent
     names, ratings, grades, or quotes.
   - If the excerpts don't cover it, say so plainly ("I don't have student feedback
     on that") — "a confident wrong answer is worse than an honest I don't know."
   - **Synthesize across opinions** (report consensus + note disagreement), don't
     cherry-pick one review.
   - **Attribute** claims to their source ("students on Rate My Professors say…",
     "the syllabus states…") and cite numeric ratings when given.
   - Distinguish opinion (reviews) from fact (syllabus).
3. **Low temperature (0.2)** to keep generation close to the retrieved text.

### Example responses (with source attribution)

**Example 1 — in-scope:** *"Is Connor Nelson worth taking?"*
> Based on the provided **Rate My Professors reviews**, the consensus is that
> Connor Nelson is not worth taking. **All 5 reviews have a quality rating of
> 1.0/5**, indicating extremely low satisfaction. Students describe the class as
> "super wack," state that Connor Nelson "teaches nothing, expects everything," and
> warn others not to take the class. One reviewer mentions the workload is like a
> "full time job plus overtime every single week." Overall the reviews are
> overwhelmingly negative…

**Example 2 — in-scope:** *"How is Linda Chattin for IEE 380?"*
> Linda Chattin for IEE 380 has received generally positive reviews, with an
> **average quality rating of 3.8/5 across the 5 reviews**. **Students on Rate My
> Professors** say she is "very solid," "very fair, very organized, and very
> manageable." However, there is a notable disagreement — one student gave her a
> 1.0/5 and called the class "ALL self study." Most found the course manageable
> (difficulty 2.0–3.0/5) and would take her again.

**Example 3 — out-of-scope (refusal):** *"What's the best dorm to live in at ASU?"*
> I don't have student feedback on that. The provided excerpts only discuss ASU
> professors and courses, but do not mention dorms.

Note how each in-scope answer attributes claims to the source type and cites the
numeric ratings, while the out-of-scope query is refused rather than answered from
the model's general knowledge.

---

## Query Interface

A **Gradio chat interface** ([`app.py`](app.py)) launched at `http://127.0.0.1:7860`.

| Field | Description |
|-------|-------------|
| **Input** (textbox) | A free-text natural-language question about an ASU CS course or professor. Multi-turn: follow-ups are rewritten into standalone queries using conversation history. |
| **Output** (chat bubble) | A grounded, source-attributed answer synthesized from the retrieved reviews/syllabi, or a plain refusal if out of scope. |
| **Sidebar** | A static "Sources" panel (r/ASU, Rate My Professors, official syllabi) and a disclaimer that answers come only from collected student opinions. |
| **Examples** | One-click starter questions (e.g. "How hard is CSE 240?"). |

### Sample interaction transcript (multi-turn, real output)

```
USER:  How hard is CSE 240?
GUIDE: Students on Reddit have mixed opinions about the difficulty of CSE 240.
       One student notes the tests are hard due to the time constraint, despite
       being open note. Another comments the class has a heavy workload with
       weekly homework but is manageable if you stay on top of it. A student who
       took CSE 230 afterward says they breezed through it because CSE 240 made
       them comfortable with pointers. Overall: challenging in workload and test
       format, but manageable with effort.

USER:  Who should I take it with?
       (condensed query → "Who is a good professor to take CSE 240 with?")
GUIDE: Based on the excerpts, students suggest considering Erik Trickel (one
       notes he had a great first lecture) or David Claveau over other options.
       However, there is no clear consensus on the single best professor.
```

The condense step ([`generator.py`](generator.py)) rewrote the pronoun-laden
follow-up "Who should I take it with?" into a standalone query before retrieval,
so the second turn correctly pulled CSE 240 *professor* threads.

---

## Evaluation Report

5 test questions, each run through the live pipeline. "Expected" comes from the
ground-truth aggregates in [`planning.md`](planning.md); "judgment" compares the
system's response to that expectation.

| # | Question | Expected | System response (summary) | Accuracy |
|---|----------|----------|---------------------------|----------|
| 1 | Is Connor Nelson worth taking? | No / polarizing (1.9/5, 21% would retake) | "Not worth taking… all retrieved reviews 1.0/5… overwhelmingly negative" | ✅ Correct verdict (couldn't cite the 1.9 / 21% aggregate — only saw 1.0 reviews) |
| 2 | What do students think of Andrea Richa? | Well-liked (4.0/5, 86% would retake) | "**Mixed opinions** — praised by some (5/5), negative for others (2/5)" | ⚠️ **Partially wrong** — hedged to "mixed" instead of the actual "well-liked" consensus (see Failure Case) |
| 3 | How hard is CSE 240? | Hard / heavy workload, weed-out | "Mixed; heavy workload and tough test format, but manageable with effort" | ✅ Mostly correct (softer than "weed-out") |
| 4 | What is CSE 310 about and is it difficult? | Data structures & algorithms; challenging | "Algorithms & data structures in C++; complicated concepts, challenging but doable with prep" | ✅ Correct |
| 5 | How is Linda Chattin for IEE 380? | Well-regarded (4.2/5, 76%) | "Generally positive, avg 3.8/5… one dissenting 1/5" | ✅ Correct verdict (3.8 vs 4.2 because it averages the top-k, not the full aggregate) |

**Score: 4 / 5 fully accurate, 1 partial miss (Richa).** This is *more* honest than
the plan's optimistic "5/5" — the live runs revealed the Richa hedge.

### Honest failure case

**Query 2, "What do students think of Andrea Richa?", returns "mixed opinions"
when the true consensus is well-liked (4.0/5, 86% would take again).**

*Why it happened:* two compounding causes.
1. **No recency weighting.** Top-k=5 retrieval pulled a spread that included two
   *decade-old* negative reviews (Dec 2014, Sep 2021) alongside recent praise.
   Ranking is by relevance, not date, so stale criticism is weighted equally with
   current sentiment.
2. **The system can't see the headline aggregate.** It synthesizes only the
   retrieved top-k, not the whole file, and the RMP parser
   ([`ingest.py`](ingest.py)) skips the file-header summary where the "4.0/5, 86%
   would take again" figure lives. So the model has no way to anchor on the
   overall verdict and instead reports the spread of the 5 chunks it sees.

*Fix:* ingest the RMP header summary as its own chunk, and/or add a recency tie-break
to retrieval. Both are noted in [`planning.md`](planning.md) → Evaluation Plan.

A second, smaller failure (Query 1 retrieval table above): the comment *"This is if
you are ser of course, not cse"* is a low-signal fragment that passed the
`min_length=40` filter and got retrieved; the LLM correctly ignored it, but it
shouldn't have ranked.

---

## Spec Reflection

**One way the spec helped.** The deliverable checklist's explicit requirements —
*labeled sample chunks*, a full *evaluation report*, and especially *"at least one
honest failure case"* — forced me to actually run the pipeline against ground truth
and write down what it gets wrong, instead of stopping at "it works on the happy
path." That requirement is what surfaced the Richa "mixed-vs-well-liked" miss and
the aggregate-stat limitation; without it I'd have shipped the plan's optimistic
"5/5" claim.

**One way implementation diverged from the spec (and why).** The starter spec set
`N_RESULTS = 3` and a pure-semantic retriever. Implementation diverged to **k = 5**
and **hybrid semantic + BM25 with RRF**, because semantic-only retrieval failed on
the two query types this domain depends on: it blurred course codes (a "CSE 240"
query pulled CSE 110 chunks) and couldn't find professor reviews whose body text
never repeats the professor's name. Adding BM25 + the contextual headers + the
course auto-filter fixed both, at the cost of more retrieval machinery than the
spec implied.

---

## AI Usage

> *(Drafted from the repo's design notes and commit history — verify/adjust before
> submitting.)*

**Instance 1 — Embedding strategy: directed "embed clean prose only," then
overrode it.** I directed the AI to write the chunker so that only the free-form
review/comment text is embedded and all structured fields go to metadata (to keep
embeddings clean). On testing, a "Connor Nelson" query returned **0/3 relevant
results**, because the professor's name lived only in metadata, which isn't
embedded. I overrode the "clean prose only" rule by adding a **contextual header**
(`_context_header` in [`ingest.py`](ingest.py)) that prepends a short identifier
line (e.g. `Rate My Professors review — Connor Nelson:`) to the *embedded* text —
which took that query to **3/3**. The AI's first version was technically cleaner but
empirically worse; I kept the data-quality intent and changed the implementation.

**Instance 2 — Retrieval: directed semantic search, revised to hybrid + course
filter.** I directed the AI to implement semantic retrieval over ChromaDB. It
worked for paraphrased opinions but cross-matched similar course codes (CSE 240 ↔
CSE 340) and missed exact-name queries. I revised the design to **fuse BM25 keyword
search with the semantic results via RRF** and added a **course auto-filter**
(`_detect_course` in [`retriever.py`](retriever.py)) that restricts retrieval when a
single course code is named — overriding the AI's initial "embeddings are enough"
approach after eval showed wrong-course bleed.

---

## Getting Started

### 1. Clone
```bash
git clone https://github.com/ateressa/The_Unofficial_Guide.git
cd The_Unofficial_Guide
```

### 2. Create a virtual environment (Python 3.12 recommended)
```bash
python3.12 -m venv .venv
source .venv/bin/activate      # Mac/Linux  (.venv\Scripts\activate on Windows)
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```
> `sentence-transformers` downloads the embedding model (~80MB) on first run, then caches it.

### 4. Add your Groq API key
```bash
cp .env.example .env   # then set GROQ_API_KEY from console.groq.com (free)
```

### 5. Run
```bash
python app.py
```
First launch ingests the corpus into ChromaDB, then opens the chat UI at `http://127.0.0.1:7860`.

---

## Project Structure

```
The_Unofficial_Guide/
├── app.py            # Gradio chat UI + startup ingestion (condense → retrieve → generate)
├── config.py         # Models, paths, collection name, top-k
├── ingest.py         # Per-source loaders + structure-aware chunking
├── retriever.py      # Embed/store + hybrid (semantic + BM25) retrieval + course filter
├── generator.py      # Grounding prompt + multi-turn query rewrite (Groq)
├── data/             # The corpus (collected by hand — see data/README.md)
│   ├── reddit/       # r/ASU threads saved via the ".json trick"
│   ├── rmp/          # Rate My Professors reviews (one .txt per professor)
│   └── pdf/          # Official course syllabi
└── planning.md       # Design doc (written before implementation)
```

## Re-ingesting After Changes

ChromaDB persists to `./chroma_db`. After changing chunking or the corpus, delete
that folder and restart so the data is re-embedded:
```bash
rm -rf chroma_db/ && python app.py
```
To inspect chunks without the UI: `python ingest.py`.
