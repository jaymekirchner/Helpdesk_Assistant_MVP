
import os
import sys
import json
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI

load_dotenv()

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

HISTORY_LIMIT = 12

if not all([SEARCH_ENDPOINT, SEARCH_KEY, SEARCH_INDEX, OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT]):
    print("Missing required environment variables. Please check your .env file.")
    sys.exit(1)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_KEY)
)

openai_client = AzureOpenAI(
    api_key=OPENAI_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=OPENAI_ENDPOINT
)

# ════════════════════════════════════════════════════
# LAYER 1 — RETRIEVAL
# ════════════════════════════════════════════════════

def get_search_results(query, top_k=5):
    """Query Azure AI Search and return top_k document chunks."""
    try:
        results = search_client.search(query, top=top_k)
        docs = []
        for doc in results:
            for field in ["content", "text", "chunk", "chunk_text"]:
                if field in doc and doc[field]:
                    docs.append(doc[field])
                    break
            else:
                docs.append(str(doc))
        return docs
    except Exception as e:
        print(f"Error querying Azure Search: {e}")
        return []


# ════════════════════════════════════════════════════
# LAYER 2 — TRIAGE (Clarification Check)
# ════════════════════════════════════════════════════

def is_query_vague(question, conversation_history):
    """
    Ask the LLM whether the query needs clarification before retrieval.
    Returns: (is_vague: bool, clarifying_question: str | None)
    """
    system_message = (
        "You are an IT support triage assistant. Decide if the user's question "
        "is too vague to answer without more detail.\n\n"
        "A query is vague if it is missing:\n"
        "- The specific application or tool involved\n"
        "- The operating system (Windows/Mac/Linux)\n"
        "- Any error messages or symptoms\n"
        "- What the user was doing when the issue occurred\n\n"
        "Examples of vague: 'VPN not working', 'Help me', 'Outlook issue'\n"
        "Examples of specific: 'Outlook crashes on Windows 11 when opening attachments', "
        "'VPN drops on Mac, error 619'\n\n"
        "If vague, respond ONLY with this JSON:\n"
        '{"vague": true, "clarifying_question": "Your single follow-up question here"}\n\n'
        "If specific enough, respond ONLY with:\n"
        '{"vague": false, "clarifying_question": null}\n\n'
        "No explanation. No markdown. JSON only."
    )

    messages = [
        {"role": "system", "content": system_message},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": question}
    ]

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        print(f"[DEBUG] Vagueness check: {raw}")
        parsed = json.loads(raw)
        return parsed.get("vague", False), parsed.get("clarifying_question", None)
    except Exception as e:
        print(f"[DEBUG] Vagueness check failed: {e} — proceeding to retrieval")
        return False, None  # Fail open


# ════════════════════════════════════════════════════
# LAYER 3 — GENERATION
# ════════════════════════════════════════════════════

def get_grounded_answer(question, context_docs, conversation_history):
    """Generate a grounded answer using retrieved context and conversation history."""
    context = "\n---\n".join(context_docs)

    system_message = (
        "You are a helpful IT support assistant. Answer the user's question using ONLY "
        "the context provided below. Use the conversation history to understand "
        "follow-up questions and references to previous answers.\n"
        "If the answer is not in the context, say: "
        "'I don't have enough information to answer that based on the available documents.'\n\n"
        f"Context:\n{context}"
    )

    messages = [
        {"role": "system", "content": system_message},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": question}
    ]

    try:
        print(f"[DEBUG] Calling deployment: {OPENAI_DEPLOYMENT}")
        print(f"[DEBUG] History in context: {min(len(conversation_history), HISTORY_LIMIT)} messages")
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.2,
            max_tokens=512
        )
        answer = response.choices[0].message.content.strip()
        print(f"[DEBUG] Response length: {len(answer)} chars")
        return answer
    except Exception as e:
        return f"Error from OpenAI: {e}"


# ════════════════════════════════════════════════════
# LAYER 4 — AGENT CONTROLLER (the brain)
# ════════════════════════════════════════════════════

def handle_user_message(user_input, conversation_history):
    """
    The Agent Controller. The single entry point for every user message.

    Decision flow:
        1. Is the query vague?
           YES → return a clarifying question, skip retrieval
           NO  → retrieve docs → generate grounded answer

    Returns:
        response      (str)  — what to show the user
        should_store  (bool) — whether this turn should be saved to history
                               (False when we're mid-clarification loop and
                                want to let main() handle storage explicitly)
    """
    print("\n[Agent Controller] Evaluating message...")

    # ── Decision 1: Does the agent need more information? ──
    is_vague, clarifying_question = is_query_vague(user_input, conversation_history)

    if is_vague and clarifying_question:
        print("[Agent Controller] Decision → CLARIFY")
        return clarifying_question, True   # store the Q&A pair so history has context

    # ── Decision 2: Proceed with retrieval + generation ──
    print("[Agent Controller] Decision → RETRIEVE + ANSWER")

    docs = get_search_results(user_input, top_k=5)

    if not docs:
        return "I couldn't find any relevant documents for your question.", True

    print(f"\nRetrieved {len(docs)} chunk(s):")
    for i, doc in enumerate(docs, 1):
        print(f"\n--- Chunk {i} ---\n{doc}")

    answer = get_grounded_answer(user_input, docs, conversation_history)
    return answer, True


# ════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════

def main():
    print("═" * 55)
    print("  Azure RAG IT Support Agent")
    print("  Memory ✓  Clarification ✓  Agent Controller ✓")
    print("═" * 55)
    print("Commands: 'exit' to quit · 'reset' to clear history\n")

    conversation_history = []

    while True:
        user_input = input("\n> ").strip()

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        if user_input.lower() == "reset":
            conversation_history = []
            print("Conversation history cleared.")
            continue

        if not user_input:
            continue

        # ✅ Single call — the controller decides everything from here
        response, should_store = handle_user_message(user_input, conversation_history)

        print(f"\nAssistant: {response}")

        # ✅ Append turn to history after response
        if should_store:
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")