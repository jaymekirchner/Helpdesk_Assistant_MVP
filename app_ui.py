import streamlit as st
import asyncio
from datetime import datetime
import sys
import os
from streamlit.errors import StreamlitAPIException

# Add the current directory to the path so we can import from this project
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the main logic from the modular entry point
APP_IMPORT_ERROR = None
try:
    from app import handle_user_message, _call_mcp_tool, _extract_mcp_records
except Exception as import_error:
    APP_IMPORT_ERROR = import_error

    async def handle_user_message(user_input, conversation_history):
        return (
            "The assistant backend failed to initialize due to a missing or broken Python package. "
            f"Startup error: {APP_IMPORT_ERROR}"
        ), False

    def _call_mcp_tool(tool_name, args):
        raise RuntimeError(f"Backend initialization failed: {APP_IMPORT_ERROR}")

    def _extract_mcp_records(result):
        return []

# Set page configuration
st.set_page_config(
    page_title="IT Helpdesk Assistant",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
<style>
    body {
        background: radial-gradient(circle at top left, #f2f8ff 0%, #dbefff 45%, #f8fafd 100%);
    }
    .main-header {
        font-size: 2.8rem;
        font-weight: 800;
        color: #0b3d91;
        text-align: center;
        letter-spacing: 0.6px;
        margin-bottom: 1rem;
        text-shadow: 0 1px 4px rgba(0,0,0,0.1);
    }
    .chat-panel {
        padding: 1.2rem;
        border-radius: 1rem;
        border: 1px solid rgba(0,48,120,0.16);
        box-shadow: 0 8px 24px rgba(15, 52, 92, 0.14);
        background: linear-gradient(145deg, rgba(255,255,255,0.95), rgba(240,248,255,0.95));
        max-height: 620px;
        overflow-y: auto;
        margin-bottom: 0.8rem;
    }
    .user-message {
        background-color: #e1f1ff;
        color: #083b73;
        padding: 0.9rem;
        border-radius: 14px;
        margin: 0.6rem 0;
        border-left: 4px solid #1e88e5;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.05);
    }
    .assistant-message {
        background-color: #f9f9fb;
        color: #294661;
        padding: 0.9rem;
        border-radius: 14px;
        margin: 0.6rem 0;
        border-left: 4px solid #388e3c;
        box-shadow: inset 0 1px 2px rgba(2,10,20,0.04);
    }
    .message-timestamp {
        font-size: 0.76rem;
        color: #5f7287;
        margin-bottom: 0.3rem;
        font-weight: 500;
    }
    .input-container {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 1rem 1.5rem;
        background: rgba(255,255,255,0.92);
        border-top: 1px solid rgba(20,74,126,0.15);
        box-shadow: 0 -6px 18px rgba(13, 44, 85, 0.12);
        z-index: 1000;
    }
    .stTextInput > div > div > input {
        font-size: 1.05rem;
        padding: 0.85rem;
        border-radius: 12px;
        border: 1px solid #c8d8eb;
        background-color: #ffffff;
        color: #000000;
    }
    .sidebar-info {
        background: linear-gradient(160deg, #dff3ff, #e9f8ff);
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid #c5e0ff;
        margin-bottom: 1rem;
        box-shadow: 0 4px 12px rgba(0, 76, 146, 0.08);
    }
    .stApp > .main > .block-container {
        padding-top: 1.2rem;
        padding-bottom: 5rem;
    }
    .stButton>button {
        border-radius: 12px;
        background: linear-gradient(130deg,#2f7ff1,#004eb3);
        color: white;
        font-weight: 650;
    }
    .stButton>button:hover {
        background: linear-gradient(130deg,#3f8ff7,#005ec8);
    }
    .top-bar {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        margin-bottom: 1rem;
        padding: 0.8rem 1rem;
        border-radius: 0.85rem;
        background: linear-gradient(110deg, #1f4f9a, #1361b4);
        color: white;
        box-shadow: 0 6px 20px rgba(7, 29, 72, 0.24);
    }
    .logo {
        font-size: 1.7rem;
        padding: 0.3rem 0.6rem;
        border-radius: 0.75rem;
        background: rgba(255,255,255,0.2);
    }
    .typing-indicator {
        animation: blink 1s infinite;
        color: #1f78d1;
    }
    @keyframes blink {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }
</style>
""", unsafe_allow_html=True)

# Top bar + helper cards
st.markdown("""
<div class='top-bar'>
    <div class='logo'>🛠️</div>
    <div>
        <h2>IT Helpdesk Assistant</h2>
        <p>Fast enterprise support powered by AI + Microsoft Agent Framework</p>
    </div>
</div>

<div style='display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem;'>
    <div style='flex:1;min-width:220px;background:#ffffff;box-shadow:0 6px 15px rgba(3,38,76,0.06);border:1px solid #def1ff;border-radius:12px;padding:16px;'>
        <h4 style='margin:0;margin-bottom:8px;color:#0b4b98;'>Quick Start</h4>
        <p style='margin:0;font-size:0.88rem;color:#405775;'>Type your issue and hit send, or press Enter to submit. The assistant responds with guided troubleshooting quickly.</p>
    </div>
    <div style='flex:1;min-width:220px;background:#ffffff;box-shadow:0 6px 15px rgba(3,38,76,0.06);border:1px solid #def1ff;border-radius:12px;padding:16px;'>
        <h4 style='margin:0;margin-bottom:8px;color:#0b4b98;'>Pro Tips</h4>
        <p style='margin:0;font-size:0.88rem;color:#405775;'>Use commands like <code>lookup user</code> or <code>check device</code> for fast task routing and <code>create ticket</code> to force escalation.</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Ensure we have typing indicator state managed
if 'typing' not in st.session_state:
    st.session_state.typing = False

def initialize_session_state():
    """Initialize session state variables"""
    if 'conversation_history' not in st.session_state:
        st.session_state.conversation_history = []
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    # add statement so that the user input is cleared after 
    if 'last_input' not in st.session_state:
        st.session_state.last_input = ""
    if 'pending_input' not in st.session_state:
        st.session_state.pending_input = ""
    # if 'health_status' not in st.session_state:
    #     st.session_state.health_status = _run_health_check()


def add_message(role, content):
    """Add a message to the conversation"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.messages.append({
        'role': role,
        'content': content,
        'timestamp': timestamp
    })


def _run_health_check():
    """Call the MCP health_check tool once and cache the result in session state."""
    if APP_IMPORT_ERROR is not None:
        return {
            "success": False,
            "error": f"Backend import failed: {APP_IMPORT_ERROR}",
            "data": {
                "status": "degraded",
                "checks": {"backend_import": "error"},
            },
        }
    try:
        result = _call_mcp_tool("health_check", {})
        records = _extract_mcp_records(result)
        envelope = records[0] if records else {}
        if isinstance(envelope, dict) and "data" in envelope:
            return envelope
        return None
    except Exception:
        return None


def handle_ui_error(error, user_message="Sorry, I encountered an error while updating the interface."):
    """Display UI-related failures in the chat and in the Streamlit error area."""
    add_message('assistant', f"{user_message} Details: {error}")
    st.error(f"{user_message} Details: {error}")

def display_chat_history():
    """Display the chat history"""
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)

    for message in st.session_state.messages:
        if message['role'] == 'user':
            st.markdown(f"""
            <div class="user-message">
                <div class="message-timestamp">You • {message['timestamp']}</div>
                {message['content']}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="assistant-message">
                <div class="message-timestamp">Assistant • {message['timestamp']}</div>
                {message['content']}
            </div>
            """, unsafe_allow_html=True)

    if st.session_state.typing:
        st.markdown("""
        <div class='assistant-message'>
            <div class='message-timestamp'>Assistant • ...</div>
            <div style='display:flex;align-items:center;gap:8px;'>
                <span>Typing</span>
                <span style='animation: blink 1s infinite;'>●</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

async def process_user_input(user_input):
    """Call the agent and append its response. User message is already in session state."""
    if not user_input.strip():
        return

    # Build history excluding the current user message (already appended before the rerun)
    conversation_history = [
        {'role': msg['role'], 'content': msg['content']}
        for msg in st.session_state.messages[:-1]
    ]

    try:
        response, should_store = await handle_user_message(user_input, conversation_history)
        add_message('assistant', response)
        if should_store:
            st.session_state.conversation_history = conversation_history + [
                {'role': 'user', 'content': user_input},
                {'role': 'assistant', 'content': response}
            ]
    except Exception as e:
        add_message('assistant', f"Sorry, I encountered an error: {str(e)}")


def submit_user_input(user_input):
    """Phase 1: add the user message immediately and rerun so it appears straight away.
    Phase 2 (pending_input processing) runs on the next render cycle."""
    add_message('user', user_input)
    st.session_state.pending_input = user_input
    st.session_state.typing = True
    st.session_state.last_input = ""
    st.rerun()

def main():
    initialize_session_state()

    # Phase 2: pending input — user message is already displayed; now fetch the agent response
    if st.session_state.get('pending_input'):
        pending = st.session_state.pending_input
        st.session_state.pending_input = ""
        try:
            asyncio.run(process_user_input(pending))
        except Exception as error:
            handle_ui_error(error, "The request could not be processed.")
        st.session_state.typing = False
        st.rerun()

    # # Sidebar
    # with st.sidebar:
    #     st.markdown("""<div class="sidebar-info">
    #         <h3 style="margin:0;">🛠️ IT Helpdesk Assistant<br>Health Check</h3>
    #     </div>""", unsafe_allow_html=True)

    #     # ── MCP Server Status ──────────────────────────────
    #     health = st.session_state.get("health_status")
    #     if health is None:
    #         st.error("⛔ MCP Server unreachable — tool calls will fail.")
    #     else:
    #         data = health.get("data") or {}
    #         checks = data.get("checks", {})
    #         if health.get("success"):
    #             st.success("✅ Server ready")
    #         else:
    #             st.warning("⚠️ Server degraded")
    #             error_details = health.get("error")
    #             if error_details:
    #                 st.error(f"Startup details: {error_details}")
    #         for dep, status in checks.items():
    #             icon = "🟢" if status in ("ok", "configured") else "🔴"
    #             st.markdown(f"{icon} **{dep}**: {status}")
    #     if st.button("🔄 Recheck"):
    #         st.session_state.health_status = _run_health_check()
    #         st.rerun()
    #     st.markdown("---")

    #     if st.button("🗑️ Clear Conversation"):
    #         try:
    #             st.session_state.conversation_history = []
    #             st.session_state.messages = []
    #             st.session_state.user_input = ""
    #             st.session_state.last_input = ""
    #             st.rerun()
    #         except StreamlitAPIException as error:
    #             handle_ui_error(error, "The conversation could not be cleared.")

    # Main content
    col_title, col_clear = st.columns([6, 1])
    with col_title:
        st.markdown('<h1 class="main-header">IT Helpdesk Assistant</h1>', unsafe_allow_html=True)
    with col_clear:
        if st.button("🗑️ Clear Conversation", key="main_clear"):
            st.session_state.conversation_history = []
            st.session_state.messages = []
            st.session_state.last_input = ""
            st.rerun()
    st.markdown("Welcome! I'm your IT support assistant. How can I help you today?")

    # Display chat history
    display_chat_history()

    # Input section
    st.markdown("---")
    with st.form(key="chat_form", clear_on_submit=True):
        col1, col2 = st.columns([4, 1])

        with col1:
            user_input = st.text_input(
                "Type your message here...",
                placeholder="Describe your IT issue or ask a question...",
                label_visibility="collapsed"
            )

        with col2:
            send_button = st.form_submit_button("Send 📤", use_container_width=True)

        # Process input
        if send_button and user_input:
            submit_user_input(user_input)


    # Improved auto-focus for the chat input box after each render
    st.markdown("""
    <script>
    // Try to focus the Streamlit chat input box reliably
    window.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            // Find the input inside the chat form
            const chatForm = window.parent.document.querySelector('form[data-testid="stForm"]');
            if (chatForm) {
                const input = chatForm.querySelector('input[type="text"]');
                if (input) { input.focus(); }
            }
        }, 100);
    });
    </script>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style='margin-top:1rem;padding:0.8rem 1rem;border-top:1px solid rgba(20,70,120,0.14);text-align:center;color:#4f637a;font-size:0.86rem;'>
        <strong>Helpdesk Assistant v1.2</strong> · Built on Azure OpenAI + Agent Framework · Powered by Streamlit
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()