"""
Answer generation for The Unofficial Guide.

Two LLM responsibilities, both on Groq (Llama-3.3-70b):

  condense_query(history, question)  - rewrite a follow-up into a standalone
                                       search query so multi-turn retrieval works
  generate_response(query, chunks, history)
                                     - write a grounded answer from the retrieved
                                       excerpts + conversation history

Grounding is the whole point: the model must answer ONLY from the retrieved
student reviews / syllabus excerpts, synthesize across opinions, and admit when
the excerpts don't cover the question rather than guessing.
"""

from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL

_client = Groq(api_key=GROQ_API_KEY)

# How many prior chat messages to carry for conversational context.
_HISTORY_TURNS = 6

_SYSTEM_PROMPT = (
    "You are The Unofficial Guide, an assistant that answers questions about ASU "
    "Computer Science courses and professors using ONLY the real student reviews "
    "and official syllabus excerpts provided to you in each message.\n\n"
    "GROUNDING RULES — follow these strictly:\n"
    "1. Use ONLY the provided excerpts. Never use prior knowledge about ASU, its "
    "courses, or its professors. Never invent professor names, ratings, grades, "
    "course details, or quotes.\n"
    "2. If the excerpts don't contain enough information to answer, say so plainly "
    "(e.g. \"I don't have student feedback on that\") instead of guessing. A "
    "confident wrong answer is worse than an honest \"I don't know.\"\n"
    "3. Most excerpts are subjective student opinions. Synthesize across them: "
    "report the general consensus and call out notable disagreement or mixed "
    "opinions — don't cherry-pick a single review.\n"
    "4. Attribute claims to their source — e.g. \"students on Rate My Professors "
    "say…\", \"a Reddit commenter notes…\", \"the syllabus states…\" — and cite the "
    "numeric ratings (quality/difficulty out of 5) when they're given.\n"
    "5. Distinguish opinion (reviews) from fact (syllabus). Don't present one "
    "student's experience as universal truth.\n"
    "6. Be concise and direct: answer the question first, then briefly support it."
)

_CONDENSE_PROMPT = (
    "Given the conversation so far and a follow-up message, rewrite the follow-up "
    "as a standalone search query that makes sense without the conversation. "
    "Resolve pronouns and references (e.g. 'is it hard?' after discussing CSE 240 "
    "becomes 'Is CSE 240 hard?'). Keep professor and course names. "
    "Output ONLY the rewritten query, nothing else."
)


def _recent_history(history):
    """Normalize Gradio history to the last few turns as clean {role, content}
    dicts. Gradio's message format carries extra keys (e.g. 'metadata',
    'options') that the Groq/OpenAI chat API rejects, so we strip to the two
    fields the API accepts."""
    if not history:
        return []
    msgs = [
        {"role": m["role"], "content": str(m["content"])}
        for m in history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    return msgs[-_HISTORY_TURNS:]


def condense_query(history, question):
    """Rewrite a follow-up question into a standalone retrieval query using the
    conversation context. Returns the original question when there's no history."""
    history = _recent_history(history)
    if not history:
        return question

    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    try:
        resp = _client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": _CONDENSE_PROMPT},
                {"role": "user", "content": f"Conversation:\n{convo}\n\nFollow-up: {question}"},
            ],
        )
        rewritten = resp.choices[0].message.content.strip()
        return rewritten or question
    except Exception:
        # If the rewrite fails for any reason, fall back to the raw question.
        return question


def _source_label(m):
    """Human-readable attribution line built from a chunk's metadata."""
    src = m.get("source")
    if src == "rmp":
        parts = [f"Rate My Professors review of {m.get('professor') or 'a professor'}"]
        if m.get("course"):
            parts.append(str(m["course"]))
        extras = []
        for key, fmt in (("quality", "quality {}/5"), ("difficulty", "difficulty {}/5"),
                         ("grade", "grade {}"), ("would_take_again", "would take again: {}"),
                         ("date", "{}")):
            if m.get(key) not in ("", None):
                extras.append(fmt.format(m[key]))
        label = ", ".join(parts)
        return f"{label} ({'; '.join(extras)})" if extras else label
    if src == "reddit":
        label = "Reddit r/ASU"
        if m.get("course"):
            label += f" — {m['course']}"
        extras = []
        if m.get("score") not in ("", None):
            extras.append(f"👍 {m['score']}")
        if m.get("date"):
            extras.append(str(m["date"]))
        return f"{label} ({', '.join(extras)})" if extras else label
    if src == "pdf":
        return f"{m.get('course', '')} official syllabus".strip()
    return str(src or "source")


def _format_context(chunks):
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] {_source_label(c['metadata'])}\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def generate_response(query, retrieved_chunks, history=None):
    """Generate a grounded answer from retrieved chunks + conversation history."""
    if not retrieved_chunks:
        return (
            "I don't have any student reviews or syllabus excerpts that cover that. "
            "Try naming a specific ASU CS course (e.g. CSE 240) or professor."
        )

    context = _format_context(retrieved_chunks)
    user_message = (
        f"Here are the retrieved excerpts:\n\n{context}\n\n"
        f"Using only these excerpts, answer the question: {query}"
    )

    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(_recent_history(history))
    messages.append({"role": "user", "content": user_message})

    response = _client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.2,
        messages=messages,
    )
    answer = response.choices[0].message.content
    return answer + _sources_footer(retrieved_chunks)


def _sources_footer(chunks):
    """A small, deduplicated 'Sources' list appended under the answer so the
    user can see exactly which reviews/syllabi the answer drew from."""
    seen, labels = set(), []
    for c in chunks:
        label = _source_label(c["metadata"])
        if label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return ""
    items = "\n".join(f"- {label}" for label in labels)
    return f"\n\n---\n**Sources**\n{items}"
