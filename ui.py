"""
Gradio Chat UI for the Azure RAG IT Helpdesk Assistant (app4.py).

Run with:
    python ui.py
"""

import asyncio
import gradio as gr

from app4 import handle_user_message

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def reset_history():
    return [], []   # chat display, conversation_history state


# ---------------------------------------------------------------------------
# Core chat handler
# ---------------------------------------------------------------------------

async def chat(user_message: str, chat_display: list, conversation_history: list):
    """
    Called on every user submission.

    Parameters
    ----------
    user_message       : raw text from the input box
    chat_display       : list of {"role": ..., "content": ...} dicts for Gradio Chatbot
    conversation_history : internal history list passed to handle_user_message
    """
    if not user_message.strip():
        return chat_display, conversation_history, ""

    response, should_store = await handle_user_message(user_message, conversation_history)

    if should_store:
        conversation_history = conversation_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response},
        ]

    chat_display = chat_display + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response},
    ]

    return chat_display, conversation_history, ""   # clear input box


# ---------------------------------------------------------------------------
# Gradio layout
# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    with gr.Blocks(
        title="IT Helpdesk Assistant",
        theme=gr.themes.Soft(primary_hue="blue"),
        css="""
            #header { text-align: center; padding: 12px 0 4px 0; }
            #header h1 { font-size: 1.6rem; font-weight: 700; margin: 0; }
            #header p  { font-size: 0.9rem; color: #555; margin: 4px 0 0 0; }
            #chatbot   { height: 520px; }
            footer     { display: none !important; }
        """,
    ) as demo:

        # ── Title ──────────────────────────────────────────────────────────
        with gr.Column(elem_id="header"):
            gr.HTML(
                "<h1>🖥️ IT Helpdesk Assistant</h1>"
                "<p>Powered by Azure AI Search · Azure OpenAI · Microsoft Agent Framework</p>"
            )

        # ── Chat area ──────────────────────────────────────────────────────
        chatbot = gr.Chatbot(
            elem_id="chatbot",
            type="messages",
            avatar_images=(None, "https://img.icons8.com/fluency/48/technical-support.png"),
            show_label=False,
            bubble_full_width=False,
        )

        # ── Input row ──────────────────────────────────────────────────────
        with gr.Row():
            txt = gr.Textbox(
                placeholder="Describe your IT issue…",
                show_label=False,
                scale=9,
                container=False,
                autofocus=True,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1, min_width=80)

        # ── Action buttons ─────────────────────────────────────────────────
        with gr.Row():
            reset_btn = gr.Button("🔄 Reset conversation", variant="secondary", size="sm")
            gr.Markdown(
                "<small>Commands understood: *lookup user*, *check device*, "
                "*create ticket*, *escalate*</small>",
                elem_id="hint",
            )

        # ── Hidden state ───────────────────────────────────────────────────
        history_state = gr.State([])   # internal conversation_history

        # ── Event wiring ───────────────────────────────────────────────────
        submit_inputs  = [txt, chatbot, history_state]
        submit_outputs = [chatbot, history_state, txt]

        txt.submit(chat, inputs=submit_inputs, outputs=submit_outputs)
        send_btn.click(chat, inputs=submit_inputs, outputs=submit_outputs)

        reset_btn.click(
            fn=reset_history,
            inputs=[],
            outputs=[chatbot, history_state],
        )

        # ── Greeting on load ──────────────────────────────────────────────
        demo.load(
            fn=lambda: (
                [{"role": "assistant",
                  "content": "Hello! I am your IT Helpdesk Assistant. How can I help you today?"}],
                [],
            ),
            outputs=[chatbot, history_state],
        )

    return demo


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ui = build_ui()
    ui.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        inbrowser=True,
    )
