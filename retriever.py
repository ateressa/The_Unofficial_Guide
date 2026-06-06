"""
Hybrid retrieval for The Unofficial Guide.

Chunks (from ingest.py) are embedded with all-MiniLM-L6-v2 and stored in a
persistent ChromaDB collection. retrieve() runs BOTH:

  - semantic search (ChromaDB / MiniLM embeddings) — catches paraphrased opinions
  - keyword search  (BM25 over the same chunks)    — pins exact course codes /
                                                      professor names

and fuses the two ranked lists with Reciprocal Rank Fusion (RRF). This is the
hybrid approach from planning.md → Retrieval Approach: semantic alone blurs
identifiers (a "CSE 240" query can match CSE 110), while keyword alone misses
paraphrase ("weed-out" vs "half the class dropped").
"""

import re

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

from config import CHROMA_COLLECTION, CHROMA_PATH, EMBEDDING_MODEL, N_RESULTS

# Embedding function and ChromaDB client are initialized once at module load.
# sentence-transformers downloads the model on first use — this may take
# 30–60 seconds the very first time. Subsequent runs use a local cache.
_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL
)
_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _client.get_or_create_collection(
    name=CHROMA_COLLECTION,
    embedding_function=_ef,
    metadata={"hnsw:space": "cosine"},
)

_BATCH = 256          # ChromaDB rejects very large single add() calls
_RRF_K = 60           # RRF damping constant (standard default)
_POOL_MULT = 4        # candidates pulled per retriever before fusion

# Lazily-built in-memory BM25 index over the collection's documents.
_bm25 = None
_bm25_ids = None
_bm25_docs = None
_bm25_metas = None

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text):
    """Lowercase word/number tokens. Keeps 'CSE 240' as ['cse', '240'] so course
    codes and professor names are matchable terms."""
    return _TOKEN_RE.findall(text.lower())


def get_collection():
    """Return the ChromaDB collection. Used by app.py during ingestion."""
    return _collection


def embed_and_store(chunks):
    """Embed a list of chunks and store them in the vector database.

    Each chunk (from ingest.chunk_document) is a dict with "text", "chunk_id",
    and a flat "metadata" dict. ChromaDB's embedding function turns the text
    into vectors automatically.
    """
    for start in range(0, len(chunks), _BATCH):
        batch = chunks[start:start + _BATCH]
        _collection.add(
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
            ids=[c["chunk_id"] for c in batch],
        )
    global _bm25
    _bm25 = None     # invalidate the keyword index; rebuilt lazily on next query
    print(f"Stored {_collection.count()} total chunks in the vector database.")


def _ensure_bm25():
    """Build the BM25 index from the collection's documents (once, cached)."""
    global _bm25, _bm25_ids, _bm25_docs, _bm25_metas
    if _bm25 is not None:
        return
    data = _collection.get(include=["documents", "metadatas"])
    _bm25_ids = data["ids"]
    _bm25_docs = data["documents"]
    _bm25_metas = data["metadatas"]
    _bm25 = BM25Okapi([_tokenize(d) for d in _bm25_docs])


def _matches_where(metadata, where):
    """Minimal metadata filter (equality on each key) for keyword results."""
    return not where or all(metadata.get(k) == v for k, v in where.items())


def _semantic_search(query, k, where):
    results = _collection.query(
        query_texts=[query],
        n_results=k,
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    return [
        {"id": cid, "text": text, "metadata": meta, "distance": dist}
        for cid, text, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def _keyword_search(query, k, where):
    _ensure_bm25()
    scores = _bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    out = []
    for i in ranked:
        if scores[i] <= 0:
            break
        if not _matches_where(_bm25_metas[i], where):
            continue
        out.append({
            "id": _bm25_ids[i], "text": _bm25_docs[i],
            "metadata": _bm25_metas[i], "bm25": float(scores[i]),
        })
        if len(out) >= k:
            break
    return out


def _rrf_fuse(rankings, n_results):
    """Reciprocal Rank Fusion: each ranking contributes 1/(K + rank) to an
    item's score. Items ranked high by both retrievers rise to the top."""
    scores, items = {}, {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            cid = item["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            items.setdefault(cid, item)
    top = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:n_results]
    return [{**items[cid], "rrf": scores[cid]} for cid in top]


# Matches a course code in a query: "CSE 240", "cse240", "mat-265", etc.
_COURSE_QUERY_RE = re.compile(r"\b(cse|mat|iee|phy|eng)\s*-?\s*(\d{3})\b", re.I)


def _detect_course(query):
    """Return the single course code mentioned in the query (normalized to
    'CSE 240'), or None if zero or more than one are mentioned. We only filter
    when exactly one course is named — a query like 'CSE 240 vs CSE 230' should
    stay unfiltered so both courses are retrievable."""
    found = {f"{m.group(1).upper()} {m.group(2)}" for m in _COURSE_QUERY_RE.finditer(query)}
    return next(iter(found)) if len(found) == 1 else None


def _run_search(query, n_results, where, mode):
    pool = max(n_results * _POOL_MULT, 10)
    if mode == "semantic":
        return _semantic_search(query, n_results, where)
    if mode == "keyword":
        return _keyword_search(query, n_results, where)
    return _rrf_fuse(
        [_semantic_search(query, pool, where), _keyword_search(query, pool, where)],
        n_results,
    )


def retrieve(query, n_results=N_RESULTS, where=None, mode="hybrid"):
    """Retrieve the top-k chunks for `query`.

    Args:
      query     : the search string.
      n_results : how many chunks to return (top-k).
      where     : optional ChromaDB/metadata equality filter, e.g.
                  {"course": "CSE 240"} or {"source": "rmp"}. When omitted, a
                  single course code mentioned in the query auto-filters to that
                  course (so "How hard is CSE 240?" doesn't pull CSE 110 chunks).
      mode      : "hybrid" (semantic + keyword, fused), "semantic", or "keyword".

    Returns a list of dicts: {"text", "metadata", ...} (the highest-ranked
    chunks). Lower semantic "distance" = more similar; "bm25"/"rrf" are scores
    where higher = better.
    """
    if _collection.count() == 0:
        return []

    course = _detect_course(query) if where is None else None
    active_where = {"course": course} if course else where

    results = _run_search(query, n_results, active_where, mode)
    if course and not results:
        # Course mentioned but nothing is tagged with it — drop the filter so we
        # still return something rather than an empty answer.
        results = _run_search(query, n_results, None, mode)

    if course:
        print(f"(course filter: {course})")
    for c in results:
        m = c["metadata"]
        label = m.get("professor") or m.get("course") or m.get("source", "?")
        score = c.get("rrf") or c.get("bm25") or c.get("distance")
        print(f"[{m.get('source')}:{label}] ({score:.3f}) {c['text'][:80]}...")
    return results
