"""
The Unofficial Guide — ASU CS course & professor advice, grounded in real
student reviews (Reddit + Rate My Professors) and official syllabi.

Pipeline per turn:
  user message + history --> condense_query() --> retrieve() --> generate_response()
"""

import gradio as gr

from ingest import load_chunks
from retriever import embed_and_store, retrieve, get_collection
from generator import condense_query, generate_response


# ---------------------------------------------------------------------------
# Ingestion — runs once on startup
# ---------------------------------------------------------------------------

def run_ingestion():
    """Load + chunk the corpus and store it in ChromaDB (skipped if populated).

    To re-ingest (e.g. after changing chunking), delete ./chroma_db and restart.
    """
    collection = get_collection()
    if collection.count() > 0:
        print(f"Vector store already populated ({collection.count()} chunks). Skipping ingestion.")
        print("To re-ingest, delete the ./chroma_db folder and restart.")
        return

    print("Ingesting corpus (reddit + rmp + pdf)...")
    chunks = load_chunks()
    if chunks:
        embed_and_store(chunks)
        print(f"Ingestion complete. {len(chunks)} chunks stored.")
    else:
        print("\n⚠️  No chunks produced — check that data/ contains documents.\n")


# ---------------------------------------------------------------------------
# Chat handler — multi-turn aware
# ---------------------------------------------------------------------------

def chat(message, history):
    if not message.strip():
        return ""
    # 1) rewrite the follow-up into a standalone query using the conversation
    search_query = condense_query(history, message)
    # 2) retrieve relevant chunks for that query
    retrieved = retrieve(search_query)
    # 3) generate a grounded answer, giving the model the conversation context
    return generate_response(message, retrieved, history)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks(
    theme=gr.themes.Soft(primary_hue="indigo"),
    title="The Unofficial Guide",
) as demo:

    gr.HTML("""
        <div style="text-align:center; padding:1.25rem 0 0.5rem;">
            <h1 style="font-size:2rem; font-weight:700; color:#312e81; margin:0;">
                🎓 The Unofficial Guide
            </h1>
            <p style="color:#6b7280; font-size:1rem; margin:0.4rem 0 0;">
                Straight talk on ASU CS courses & professors — from real student reviews.
            </p>
        </div>
    """)

    with gr.Row():
        with gr.Column(scale=3):
            gr.ChatInterface(
                fn=chat,
                type="messages",
                chatbot=gr.Chatbot(
                    height=440,
                    type="messages",
                    placeholder=(
                        "<div style='text-align:center; color:#9ca3af; margin-top:3rem;'>"
                        "Ask about a course or professor — workload, difficulty, who to take 🎯"
                        "</div>"
                    ),
                ),
                textbox=gr.Textbox(
                    placeholder='e.g. "How hard is CSE 240?" then "who should I take it with?"',
                    container=False,
                    scale=7,
                ),
                examples=[
                    "How hard is CSE 240?",
                    "Is Connor Nelson worth taking?",
                    "What do students think of Andrea Richa?",
                    "What is CSE 310 about and is it difficult?",
                    "How is Linda Chattin for IEE 380?",
                    "Which professor should I take for MAT 265?",
                    "Is CSE 110 a good first programming course?",
                ],
                cache_examples=False,
            )

        with gr.Column(scale=1, min_width=180):
            gr.HTML("""
                <div style="background:#f5f3ff; border:1px solid #ddd6fe;
                            border-radius:10px; padding:1rem; margin-top:0.5rem;">
                    <p style="font-size:0.8rem; font-weight:700; color:#4c1d95;
                               margin:0 0 0.5rem; letter-spacing:0.05em;">
                        📚 SOURCES
                    </p>
                    <ul style="font-size:0.85rem; color:#5b21b6; list-style:none;
                                padding:0; margin:0; line-height:1.8;">
                        <li>💬 r/ASU threads</li>
                        <li>⭐ Rate My Professors</li>
                        <li>📄 Official syllabi</li>
                    </ul>
                    <hr style="border:none; border-top:1px solid #ddd6fe; margin:0.75rem 0;">
                    <p style="font-size:0.75rem; color:#7c3aed; margin:0; line-height:1.5;">
                        Answers come only from collected student reviews and syllabi.
                        These are student opinions — if the sources don't cover it,
                        the Guide will say so.
                    </p>
                </div>
            """)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  The Unofficial Guide — starting up")
    print("=" * 50 + "\n")
    run_ingestion()
    demo.launch()
