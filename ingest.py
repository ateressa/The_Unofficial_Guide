"""
Ingestion for The Unofficial Guide.

The corpus has three source types, each with a different structure, so we use a
hybrid, structure-aware strategy (see planning.md → Chunking Strategy):

  data/reddit/*.json  → one chunk per post / per comment   (the .json trick)
  data/rmp/*.txt      → one chunk per professor review      (record split)
  data/pdf/*.pdf      → recursive character split           (long syllabi)

The pipeline stays in two stages so parsing and chunking can be tuned
independently:

  load_documents(DATA_PATH) -> [ {text, id, metadata}, ... ]   # raw docs
  chunk_document(doc)       -> [ {text, chunk_id, metadata}, ... ]

Every chunk emits the same shape regardless of source, so the embedding /
storage step downstream never has to care where a chunk came from. Source-
specific fields (quality, difficulty, grade, author, score, date, …) are
extracted into `metadata` rather than embedded as text, which keeps the
embeddings clean and enables later metadata filtering.
"""

import os
import re
import json
import glob
import datetime

from config import DATA_PATH

# --- chunking knobs (see planning.md) ---
REDDIT_MIN_LEN = 40       # drop low-signal comments ("lol same")
REDDIT_MAX_LEN = 600      # above this, a comment gets the recursive fallback
REDDIT_OVERLAP = 80
RMP_MIN_LEN = 10          # drop empty / junk review bodies
PDF_CHUNK_SIZE = 900      # syllabi need more surrounding context
PDF_OVERLAP = 120


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _course_from_name(name):
    """Pull a course code like 'CSE 240' out of a filename or text token.

    Handles 'cse240', 'cse_240', 'CSE450', 'mat_265', etc. Returns '' if none.
    """
    m = re.search(r"(cse|mat|iee|phy|eng)[\s_]?(\d{3})", name, re.IGNORECASE)
    return f"{m.group(1).upper()} {m.group(2)}" if m else ""


def _utc_to_date(created_utc):
    """Reddit created_utc (float seconds) -> 'YYYY-MM-DD' string, or ''."""
    try:
        return datetime.datetime.fromtimestamp(
            float(created_utc), tz=datetime.timezone.utc
        ).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _clean_meta(meta):
    """ChromaDB metadata must be flat scalars (str/int/float/bool). Coerce
    None -> '' and stringify anything non-scalar so storage never errors."""
    out = {}
    for k, v in meta.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _break_long(line, size):
    """Break a single over-long line on sentence, then word, boundaries —
    never mid-word. Used for blobs with no line breaks (e.g. a long Reddit
    comment) or an unusually long syllabus line."""
    parts, buf = [], ""
    for piece in re.split(r"(?<=[.!?])\s+", line):       # sentences first
        if len(buf) + len(piece) + 1 <= size:
            buf = f"{buf} {piece}".strip()
            continue
        if buf:
            parts.append(buf); buf = ""
        if len(piece) <= size:
            buf = piece
        else:                                            # fall back to words
            for word in piece.split(" "):
                if len(buf) + len(word) + 1 <= size:
                    buf = f"{buf} {word}".strip()
                else:
                    if buf:
                        parts.append(buf)
                    buf = word
    if buf:
        parts.append(buf)
    return parts


def _split_text(text, size, overlap):
    """Line- and sentence-aware splitter. Breaks the text into lines (and
    sub-breaks any line longer than `size` on sentence/word boundaries), then
    greedily packs lines into <= `size` chunks. Overlap is carried as whole
    trailing lines, so a chunk boundary never lands mid-word."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    # 1) atoms = non-empty lines, with any over-long line pre-split safely
    lines = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        lines.extend([ln] if len(ln) <= size else _break_long(ln, size))

    # 2) greedily pack lines, repeating trailing lines (<= overlap) into the next
    chunks, cur, cur_len = [], [], 0
    for ln in lines:
        add = len(ln) + (1 if cur else 0)
        if cur_len + add > size and cur:
            chunks.append("\n".join(cur))
            tail, tlen = [], 0
            for prev in reversed(cur):
                if tlen + len(prev) + 1 > overlap:
                    break
                tail.insert(0, prev); tlen += len(prev) + 1
            cur, cur_len = tail, tlen
        cur.append(ln); cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# 1. Reddit  (data/reddit/*.json — the ".json trick" structure)
# ---------------------------------------------------------------------------

def _walk_comments(children, out):
    """Recursively collect real comments from a Reddit listing's children."""
    for child in children:
        if child.get("kind") != "t1":      # skip 'more' stubs, etc.
            continue
        d = child.get("data", {})
        body = (d.get("body") or "").strip()
        if body and body not in ("[deleted]", "[removed]"):
            out.append({
                "body": body,
                "author": d.get("author", ""),
                "score": d.get("score", 0),
                "date": _utc_to_date(d.get("created_utc")),
            })
        replies = d.get("replies")
        if isinstance(replies, dict):
            _walk_comments(replies.get("data", {}).get("children", []), out)


def _load_reddit(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    course = _course_from_name(stem)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    post = data[0]["data"]["children"][0]["data"]
    title = (post.get("title") or "").strip()
    permalink = f"https://reddit.com{post.get('permalink', '')}"
    docs = []

    # The post itself (title + selftext) is one document.
    selftext = (post.get("selftext") or "").strip()
    post_text = f"{title}\n\n{selftext}".strip() if selftext else title
    docs.append({
        "text": post_text,
        "id": f"reddit_{stem}_post",
        "metadata": _clean_meta({
            "source": "reddit", "kind": "post", "course": course,
            "thread_title": title, "author": post.get("author", ""),
            "score": post.get("score", 0), "date": _utc_to_date(post.get("created_utc")),
            "ref": permalink,
        }),
    })

    # Each comment is its own document (so a chunk never blends two authors).
    comments = []
    _walk_comments(data[1]["data"]["children"], comments)
    for i, c in enumerate(comments):
        if len(c["body"]) < REDDIT_MIN_LEN:
            continue
        docs.append({
            "text": c["body"],
            "id": f"reddit_{stem}_c{i}",
            "metadata": _clean_meta({
                "source": "reddit", "kind": "comment", "course": course,
                "thread_title": title, "author": c["author"],
                "score": c["score"], "date": c["date"], "ref": permalink,
            }),
        })
    return docs


# ---------------------------------------------------------------------------
# 2. Rate My Professors  (data/rmp/*.txt — repeating review records)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}(st|nd|rd|th)?,\s+\d{4}$")
_COURSE_RE = re.compile(r"^[A-Z]{2,4}\s?\d{3}[A-Z]?$")
_RMP_FIELDS = ("For Credit", "Attendance", "Would Take Again", "Grade", "Textbook")


def _is_float(s):
    try:
        float(s.strip())
        return True
    except (ValueError, AttributeError):
        return False


def _is_review_start(lines, i):
    """A review record begins with: Quality / <num> / Difficulty / <num>."""
    return (i + 3 < len(lines)
            and lines[i].strip() == "Quality" and _is_float(lines[i + 1])
            and lines[i + 2].strip() == "Difficulty" and _is_float(lines[i + 3]))


def _rmp_professor(lines):
    """Professor name is the line just before 'Professor in the … department'."""
    for i, ln in enumerate(lines):
        if ln.startswith("Professor in the") and i > 0:
            return lines[i - 1].strip()
    return ""


def _load_rmp(path):
    stem = os.path.splitext(os.path.basename(path))[0]   # e.g. rmp_richa_cse
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    professor = _rmp_professor(lines)
    docs = []
    i, n, idx = 0, len(lines), 0

    while i < n:
        if not _is_review_start(lines, i):
            i += 1
            continue

        quality, difficulty = float(lines[i + 1]), float(lines[i + 3])
        j = i + 4
        course, date, fields = "", "", {}

        if j < n and _COURSE_RE.match(lines[j].strip()):
            course = lines[j].strip(); j += 1
        if j < n and _DATE_RE.match(lines[j].strip()):
            date = lines[j].strip(); j += 1
        while j < n and any(lines[j].startswith(k) for k in _RMP_FIELDS):
            key, _, val = lines[j].partition(":")
            fields[key.strip()] = val.strip(); j += 1

        # Body runs until the "Thumbs up" footer or the next review record.
        body = []
        while j < n and lines[j].strip() != "Thumbs up" and not _is_review_start(lines, j):
            if lines[j].strip():
                body.append(lines[j].strip())
            j += 1

        # The review sentence(s) are the long line(s); short lines are RMP tags.
        review_parts = [b for b in body if len(b) > 45]
        tags = [b for b in body if len(b) <= 45]
        review_text = " ".join(review_parts).strip()
        if not review_text and body:                  # all-short edge case
            review_text = max(body, key=len)
            tags = [b for b in body if b != review_text]

        i = j
        if len(review_text) < RMP_MIN_LEN:
            continue

        docs.append({
            "text": review_text,
            "id": f"{stem}_{idx}",
            "metadata": _clean_meta({
                "source": "rmp", "professor": professor,
                "course": _course_from_name(course) or course,
                "quality": quality, "difficulty": difficulty,
                "date": date, "grade": fields.get("Grade", ""),
                "would_take_again": fields.get("Would Take Again", ""),
                "tags": ", ".join(tags), "ref": os.path.basename(path),
            }),
        })
        idx += 1
    return docs


# ---------------------------------------------------------------------------
# 3. PDF syllabi  (data/pdf/*.pdf — long continuous documents)
# ---------------------------------------------------------------------------

# Week-by-week schedule tables don't linearize into usable text (they flatten
# to "Week Topics Reading … 1 Performance 1.1-1.7"), so we drop them. We detect
# the table header (a "Week … Dates/Reading/Modules" row) and remove it plus the
# contiguous schedule rows that follow, keeping all surrounding prose.
_SCHED_HEADER = re.compile(r"\bWeek\b.*\b(Topics|Reading|Modules|Dates)\b", re.I)
_SCHED_ROW = re.compile(
    r"[A-Z][a-z]{2}\s+\d{1,2}\s*[-–]"      # date range, e.g. "Jan 13 - 20"
    r"|Chapter\s+\d"                        # "Chapter 2 - …"
    r"|^\d{1,2}\s"                          # leading week number
    r"|\d\.\d"                              # reading section, e.g. "1.1-1.7"
)


def _strip_schedule_table(text):
    lines = text.split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        if _SCHED_HEADER.search(lines[i]):
            # also drop the schedule intro/header lines we already kept
            while out and re.search(r"course schedule|tentative", out[-1], re.I):
                out.pop()
            i += 1                                   # skip the table header row
            while i < n and (_SCHED_ROW.search(lines[i]) or len(lines[i].split()) <= 2):
                i += 1                               # skip contiguous table rows
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _load_pdf(path):
    try:
        import pdfplumber
    except ImportError as e:
        raise ImportError(
            "pdfplumber is required to ingest PDFs. Run: pip install pdfplumber"
        ) from e

    stem = os.path.splitext(os.path.basename(path))[0]
    with pdfplumber.open(path) as pdf:
        # x_tolerance=1: these syllabi pack glyphs tightly; the default tolerance
        # drops word boundaries ("RyanMeuth"), which wrecks keyword/semantic
        # retrieval. A tighter tolerance restores the spaces.
        text = "\n".join(
            (page.extract_text(x_tolerance=1) or "") for page in pdf.pages
        )
    text = _strip_schedule_table(text)

    return [{
        "text": text.strip(),
        "id": stem,
        "metadata": _clean_meta({
            "source": "pdf", "kind": "syllabus",
            "course": _course_from_name(stem),
            "ref": os.path.basename(path),
        }),
    }]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# subfolder -> (glob pattern, loader)
_LOADERS = {
    "reddit": ("*.json", _load_reddit),
    "rmp": ("*.txt", _load_rmp),
    "pdf": ("*.pdf", _load_pdf),
}


def load_documents(data_path=DATA_PATH):
    """Walk data/, dispatch each file to its source-specific loader, and return
    a flat list of raw documents: {text, id, metadata}.

    De-duplicated on (ref, text): the same thread is sometimes saved under two
    filenames (e.g. a prof-review thread also saved as a course thread), which
    would otherwise embed the same comments twice. Keying on the source ref
    (permalink / filename) keeps identical-but-genuinely-different reviews from
    different professors, since those have different refs.
    """
    documents = []
    counts = {}
    for source, (pattern, loader) in _LOADERS.items():
        folder = os.path.join(data_path, source)
        if not os.path.isdir(folder):
            continue
        for filepath in sorted(glob.glob(os.path.join(folder, pattern))):
            docs = loader(filepath)
            documents.extend(docs)
            counts[source] = counts.get(source, 0) + len(docs)

    seen, deduped = set(), []
    for d in documents:
        key = (d["metadata"].get("ref", ""), d["text"].strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)

    dropped = len(documents) - len(deduped)
    print(f"Loaded {len(deduped)} documents: {counts}" +
          (f" (dropped {dropped} duplicates)" if dropped else ""))
    return deduped


def _context_header(meta):
    """A short identifier line prepended to each chunk's *embedded* text.

    Pure semantic search blurs exact names/codes (a query for "Connor Nelson"
    can't find a review whose text never says "Nelson"). Embedding a small
    professor/course header makes those identifiers part of the vector, which
    sharply improves retrieval on name/course queries (a.k.a. contextual
    retrieval). The same fields also live in metadata for filtering/attribution.
    """
    source = meta.get("source")
    course = meta.get("course", "")
    if source == "rmp":
        prof = meta.get("professor", "")
        who = ", ".join(p for p in (prof, course) if p)
        return f"Rate My Professors review — {who}:" if who else "Rate My Professors review:"
    if source == "reddit":
        return f"{course} — Reddit r/ASU:" if course else "Reddit r/ASU:"
    if source == "pdf":
        return f"{course} course syllabus:" if course else "Course syllabus:"
    return ""


def chunk_document(doc):
    """Split one raw document into embed-ready chunks. Source-driven:

      rmp     -> one chunk (the review is already atomic)
      reddit  -> one chunk, unless a long comment needs splitting
      pdf     -> recursive character split (~900 chars / 120 overlap)

    Each chunk's text is prefixed with a context header (see _context_header).
    """
    source = doc["metadata"].get("source")
    text = doc["text"].strip()
    if not text:
        return []

    if source == "pdf":
        pieces = _split_text(text, PDF_CHUNK_SIZE, PDF_OVERLAP)
    elif source == "reddit" and len(text) > REDDIT_MAX_LEN:
        pieces = _split_text(text, REDDIT_MAX_LEN, REDDIT_OVERLAP)
    else:
        pieces = [text]

    header = _context_header(doc["metadata"])
    out = []
    for k, piece in enumerate(pieces):
        chunk_id = doc["id"] if len(pieces) == 1 else f"{doc['id']}_{k}"
        out.append({
            "text": f"{header}\n{piece}" if header else piece,
            "chunk_id": chunk_id,
            "metadata": doc["metadata"],
        })
    return out


def load_chunks(data_path=DATA_PATH):
    """Convenience: load + chunk everything into one flat list of chunks."""
    chunks = []
    for doc in load_documents(data_path):
        chunks.extend(chunk_document(doc))
    print(f"Produced {len(chunks)} chunks.")
    return chunks


if __name__ == "__main__":
    # Quick self-test: python ingest.py
    all_chunks = load_chunks()
    by_source = {}
    for c in all_chunks:
        s = c["metadata"].get("source", "?")
        by_source[s] = by_source.get(s, 0) + 1
    print("Chunks by source:", by_source)
    if all_chunks:
        ex = all_chunks[0]
        print("\nExample chunk:")
        print(" chunk_id:", ex["chunk_id"])
        print(" metadata:", ex["metadata"])
        print(" text:", ex["text"][:200], "...")
