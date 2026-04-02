import streamlit as st
import asyncio
from datetime import datetime
import sys
import os
from streamlit.errors import StreamlitAPIException

# Add the current directory to the path so we can import from this project
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the main logic from the MCP-enabled app5 module
from old_files.app5_ma_experimental import handle_user_message

# Set page configuration
st.set_page_config(
    page_title="IT Helpdesk Assistant",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .chat-container {
        max-height: 600px;
        overflow-y: auto;
        padding: 1rem;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        background-color: #f9f9f9;
    }
    .user-message {
        background-color: #e3f2fd;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
        border-left: 4px solid #2196f3;
    }
    .assistant-message {
        background-color: #f5f5f5;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
        border-left: 4px solid #4caf50;
    }
    .message-timestamp {
        font-size: 0.8rem;
        color: #666;
        margin-bottom: 0.5rem;
    }
    .input-container {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background-color: white;
        padding: 1rem;
        border-top: 1px solid #e0e0e0;
        z-index: 1000;
    }
    .stTextInput > div > div > input {
        font-size: 1.1rem;
        padding: 0.75rem;
    }
    .sidebar-info {
        background-color: #f0f8ff;
        padding: 1rem;
        border-radius: 5px;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

def initialize_session_state():
    """Initialize session state variables"""
    if 'conversation_history' not in st.session_state:
        st.session_state.conversation_history = []
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    # add statement so that the user input is cleared after 
    if 'last_input' not in st.session_state:
        st.session_state.last_input = ""

def add_message(role, content):
    """Add a message to the conversation"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.messages.append({
        'role': role,
        'content': content,
        'timestamp': timestamp
    })


def handle_ui_error(error, user_message="Sorry, I encountered an error while updating the interface."):
    """Display UI-related failures in the chat and in the Streamlit error area."""
    add_message('assistant', f"{user_message} Details: {error}")
    st.error(f"{user_message} Details: {error}")

def display_chat_history():
    """Display the chat history"""
    try:
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

        st.markdown('</div>', unsafe_allow_html=True)
    except StreamlitAPIException as error:
        st.error(f"Unable to render chat history: {error}")

async def process_user_input(user_input):
    """Process user input and get assistant response"""
    if not user_input.strip():
        return

    # Add user message to history
    add_message('user', user_input)

    # Convert messages to the format expected by app4.py
    conversation_history = [
        {'role': msg['role'], 'content': msg['content']}
        for msg in st.session_state.messages[:-1]  # Exclude the current user message
    ]

    # Get assistant response
    with st.spinner("Assistant is thinking..."):
        try:
            response, should_store = await handle_user_message(user_input, conversation_history)

            # Add assistant response
            add_message('assistant', response)

            # Update conversation history for app4.py
            if should_store:
                st.session_state.conversation_history = conversation_history + [
                    {'role': 'user', 'content': user_input},
                    {'role': 'assistant', 'content': response}
                ]

        except Exception as e:
            error_msg = f"Sorry, I encountered an error: {str(e)}"
            add_message('assistant', error_msg)


def submit_user_input(user_input):
    """Run one submission cycle and reset input state safely."""
    try:
        asyncio.run(process_user_input(user_input))
        st.session_state.user_input = ""
        st.session_state.last_input = ""
        st.rerun()
    except StreamlitAPIException as error:
        st.session_state.user_input = user_input
        st.session_state.last_input = user_input
        handle_ui_error(error, "The chat input could not be submitted.")
    except Exception as error:
        st.session_state.user_input = user_input
        st.session_state.last_input = user_input
        handle_ui_error(error, "The request could not be processed.")

def main():
    initialize_session_state()

    # Sidebar
    with st.sidebar:
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.markdown("### 🛠️ IT Helpdesk Assistant")
        st.markdown("**Features:**")
        st.markdown("- Knowledge base search")
        st.markdown("- User lookup")
        st.markdown("- Device status check")
        st.markdown("- Ticket creation")
        st.markdown("- Smart escalation")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("### 📋 Commands")
        st.markdown("- Type your IT question")
        st.markdown("- 'lookup user [username]'")
        st.markdown("- 'check device [device_id]'")
        st.markdown("- 'create ticket' for escalation")

        if st.button("🗑️ Clear Conversation"):
            try:
                st.session_state.conversation_history = []
                st.session_state.messages = []
                st.session_state.user_input = ""
                st.session_state.last_input = ""
                st.rerun()
            except StreamlitAPIException as error:
                handle_ui_error(error, "The conversation could not be cleared.")

    # Main content
    st.markdown('<h1 class="main-header">IT Helpdesk Assistant</h1>', unsafe_allow_html=True)
    st.markdown("Welcome! I'm your IT support assistant. How can I help you today?")

    # Display chat history
    display_chat_history()

    # Input section
    st.markdown("---")
    col1, col2 = st.columns([4, 1])

    with col1:
        user_input = st.text_input(
            "Type your message here...",
            key="user_input",
            placeholder="Describe your IT issue or ask a question...",
            label_visibility="collapsed"
        )

    with col2:
        send_button = st.button("Send 📤", use_container_width=True)

    # Process input
    if send_button and user_input:
        submit_user_input(user_input)

    # Handle Enter key press
    if user_input and st.session_state.get('last_input') != user_input:
        st.session_state.last_input = user_input
        submit_user_input(user_input)

if __name__ == "__main__":
    main()