from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL

_client = Groq(api_key=GROQ_API_KEY)

_SYSTEM_PROMPT = (
    "You are a board game rules reference. The retrieved rule excerpts below are your only permitted source of information.\n\n"
    "Do not use your training knowledge of board games for any purpose: not to fill gaps in the retrieved text, "
    "not to add context, not to correct the excerpts, and not to infer answers from partial information. "
    "Answer only what the excerpts explicitly state. If they do not contain a clear answer, say so.\n\n"
    "When you answer, state which game each answer comes from. "
    "If the question names a specific game, only use chunks from that game. "
    "If no game is specified, answer for every game represented in the retrieved chunks, labeled by game name."
)


def _format_context(chunks):
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"Chunk {i} | Game: {chunk['game']} | Distance: {chunk['distance']:.2f}"
        parts.append(f"{header}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def generate_response(query, retrieved_chunks):
    """
    Generate a grounded answer from retrieved rule chunks.

    TODO — Milestone 3:

    `retrieved_chunks` is the list returned by retrieve(). Each item is a dict:
      - "text"     : the chunk text
      - "game"     : the game name
      - "distance" : similarity score (you can use this to filter weak matches)

    Before writing code, talk through these with your group:
      - How will you format the chunks into a context block for the prompt?
      - What instructions will stop the model from answering beyond what the
        rules say? (Grounding is the whole point — a confident wrong answer
        is worse than an honest "I don't know.")
      - How will you surface which game each answer comes from?

    Your response should:
      1. Answer using only the retrieved context — not the model's general knowledge
      2. Make clear which game the answer comes from
      3. Say so clearly when the answer isn't in the loaded rules

    Return the response as a plain string.
    """
    if not retrieved_chunks:
        return (
            "I couldn't find anything relevant in the loaded rule books. "
            "Try rephrasing your question — or check that your ingestion pipeline is working."
        )

    context = _format_context(retrieved_chunks)
    user_message = f"Retrieved rule excerpts:\n\n{context}\n\nQuestion: {query}"

    response = _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    return response.choices[0].message.content
