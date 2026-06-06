# 🎓 The Unofficial Guide

> Straight talk on ASU Computer Science courses & professors — from real student reviews, not the course catalog.

The Unofficial Guide answers natural-language questions about the courses ASU CS
(BS) majors actually have to take — *how hard is it, who should I take it with,
is it a weed-out?* — using a Retrieval-Augmented Generation (RAG) pipeline over
**real student experiences**: r/ASU threads, Rate My Professors reviews, and
official course syllabi. Answers are **grounded in the collected sources only**;
if the sources don't cover something, it says so instead of guessing.

---

## How it works

A five-stage RAG pipeline (see [`planning.md`](planning.md) for the full design):

```
Documents ──► Chunking ──► Embedding + Vector Store ──► Retrieval ──► Generation
 reddit/rmp/   per-source    all-MiniLM-L6-v2            hybrid:        Groq
 pdf (custom   structure-    + ChromaDB (cosine)         semantic +     Llama-3.3-70b
 Python)       aware                                     BM25 (RRF)
```

Key design choices:

- **Structure-aware chunking** — one chunk per RMP review, one per Reddit
  comment, recursive splitting for syllabi. Source fields (difficulty, grade,
  score, date, course) are extracted into metadata, and a short context header
  (e.g. `Rate My Professors review — Connor Nelson:`) is embedded so exact
  names/codes are searchable.
- **Hybrid retrieval** — dense semantic search (catches paraphrased opinions)
  fused with BM25 keyword search (pins exact course codes & professor names) via
  reciprocal-rank fusion.
- **Course auto-filter** — a query naming one course (e.g. "How hard is CSE 240?")
  filters retrieval to that course so it doesn't pull in similarly-worded
  comments about other classes.
- **Grounded generation** — the LLM answers only from retrieved excerpts,
  synthesizes across opinions, attributes claims, and refuses out-of-corpus
  questions.
- **Multi-turn** — follow-ups ("who should I take it with?") are rewritten into
  standalone queries using the conversation history.

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/ateressa/The_Unofficial_Guide.git
cd The_Unofficial_Guide
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
# or: .venv\Scripts\activate   # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` downloads the embedding model (~80MB) on
> first run. This happens once, then it's cached locally.

### 4. Add your Groq API key

```bash
cp .env.example .env
```

Open `.env` and set your key from [console.groq.com](https://console.groq.com)
(free, no credit card).

### 5. Run the app

```bash
python app.py
```

On first launch it ingests the corpus into ChromaDB (a few seconds), then opens
the chat UI in your browser at `http://127.0.0.1:7860`.

---

## Project Structure

```
The_Unofficial_Guide/
├── app.py            # Gradio chat UI + startup ingestion (condense → retrieve → generate)
├── config.py         # Models, paths, collection name, top-k
├── ingest.py         # Per-source loaders + chunking → embed-ready chunks
├── retriever.py      # Embed/store + hybrid (semantic + BM25) retrieval + course filter
├── generator.py      # Grounding prompt + multi-turn query rewrite (Groq)
├── data/             # The corpus (collected by hand — see data/README.md)
│   ├── reddit/       # r/ASU threads saved via the ".json trick"
│   ├── rmp/          # Rate My Professors reviews (one .txt per professor)
│   └── pdf/          # Official course syllabi
└── planning.md       # Design doc: domain, chunking, retrieval, evaluation, architecture
```

---

## Data Sources

| Source | What | Format |
|--------|------|--------|
| **r/ASU threads** | Candid, course-level student experiences | `.json` (post + comments) |
| **Rate My Professors** | Professor-specific reviews with ratings | `.txt`, one per professor |
| **Course syllabi** | Official course structure (grading, policies) | `.pdf` |

The corpus is deepest on CSE 240 and CSE 310, with broader coverage of CS core
professors and the required math/stats courses. See [`data/README.md`](data/README.md)
for collection notes and naming conventions.

---

## Example Questions

- "How hard is CSE 240?"
- "Is Connor Nelson worth taking?"
- "What do students think of Andrea Richa?"
- "What is CSE 310 about and is it difficult?"
- "How is Linda Chattin for IEE 380?" → then *"who else teaches it?"* (multi-turn)

---

## Re-ingesting After Changes

ChromaDB persists to `./chroma_db`. After changing chunking or the corpus,
delete that folder and restart so the data is re-embedded:

```bash
rm -rf chroma_db/   # Mac/Linux
python app.py
```

To inspect the chunks without launching the UI:

```bash
python ingest.py            # counts + an example chunk per source
```
