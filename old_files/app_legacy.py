import os
import sys
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI  # ✅ Clean import, new SDK style only

# Load environment variables from .env file
load_dotenv()

# Azure Search configuration
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

# Azure OpenAI configuration
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# Validate environment variables
if not all([SEARCH_ENDPOINT, SEARCH_KEY, SEARCH_INDEX, OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT]):
    print("Missing required environment variables. Please check your .env file.")
    sys.exit(1)

######################################################################################################################################################################################

HISTORY_LIMIT = 12  # ✅ Max number of messages to keep (6 turns = 12 messages)


# Initialize Azure Search client
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_KEY)
)

# ✅ Initialize AzureOpenAI client ONCE at module level (new SDK style only)
openai_client = AzureOpenAI(
    api_key=OPENAI_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=OPENAI_ENDPOINT
)

def get_search_results(query, top_k=5):
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

def is_query_vague(question, conversation_history):
    """
    Ask the LLM to decide if the query is too vague to answer without clarification.
    Returns a tuple: (is_vague: bool, clarifying_question: str | None)
    """
    system_message = (
        "You are an IT support triage assistant. Your job is to decide whether a user's "
        "question is too vague to answer accurately without more information.\n\n"
        "A query is vague if it lacks key details such as:\n"
        "- The specific application or tool involved\n"
        "- The operating system (Windows/Mac/Linux)\n"
        "- Any error messages or symptoms\n"
        "- What the user was trying to do when the issue occurred\n\n"
        "Examples of vague queries: 'VPN not working', 'Help me', 'Outlook issue', 'it keeps crashing'\n"
        "Examples of specific queries: 'Outlook crashes on Windows 11 when opening attachments', "
        "'VPN disconnects after 10 minutes on Mac, error code 619'\n\n"
        "If the query is vague, respond with JSON in this exact format:\n"
        '{"vague": true, "clarifying_question": "Your single follow-up question here"}\n\n'
        "If the query is specific enough, respond with:\n"
        '{"vague": false, "clarifying_question": null}\n\n'
        "Respond ONLY with the JSON object. No explanation, no markdown."
    )

    # ✅ Include recent history so the LLM understands follow-up context
    messages = [
        {"role": "system", "content": system_message},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": question}
    ]

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0,        # ✅ Zero temp for deterministic classification
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        print(f"[DEBUG] Vagueness check response: {raw}")

        import json
        parsed = json.loads(raw)
        return parsed.get("vague", False), parsed.get("clarifying_question", None)
    except Exception as e:
        print(f"[DEBUG] Vagueness check failed: {e} — skipping clarification")
        return False, None  # ✅ Fail open: if check breaks, just proceed to answer


def get_grounded_answer(question, context_docs, conversation_history):
    """
    Send context, conversation history, and question to Azure OpenAI.
    """
    context = "\n---\n".join(context_docs)

    system_message = (
        "You are a helpful IT support assistant. Answer the user's question using ONLY "
        "the context provided below. You also have access to the conversation history "
        "so you can understand follow-up questions and references to previous answers. "
        "If the answer cannot be found in the context, say "
        "'I don't have enough information to answer that based on the available documents.'\n\n"
        f"Context:\n{context}"
    )

    messages = [
        {"role": "system", "content": system_message},
        *conversation_history[-HISTORY_LIMIT:],   # ✅ Sliding window of last 12 messages
        {"role": "user", "content": question}
    ]

    try:
        print(f"\n[DEBUG] Calling deployment: {OPENAI_DEPLOYMENT}")
        print(f"[DEBUG] Conversation turns in context: {min(len(conversation_history), HISTORY_LIMIT)}")
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


def main():
    print("Azure RAG IT Support Agent — with Memory & Clarification")
    print("Type your question (or 'exit' to quit, 'reset' to clear history):\n")

    conversation_history = []

    while True:
        question = input("\n> ").strip()

        if question.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        if question.lower() == "reset":
            conversation_history = []
            print("Conversation history cleared.")
            continue

        if not question:
            continue

        # ──────────────────────────────────────────────
        # STEP 1: Check if the query needs clarification
        # ──────────────────────────────────────────────
        print("\n[Checking query clarity...]")
        is_vague, clarifying_question = is_query_vague(question, conversation_history)

        if is_vague and clarifying_question:
            print(f"\nAssistant: {clarifying_question}")

            # ✅ Store the vague question and clarifying response in history
            # so the next message has full context of what was asked and why
            conversation_history.append({"role": "user", "content": question})
            conversation_history.append({"role": "assistant", "content": clarifying_question})
            continue  # ✅ Skip retrieval — wait for the user's clarified answer

        # ──────────────────────────────────────────────
        # STEP 2: Retrieve relevant documents
        # ──────────────────────────────────────────────
        print("\nSearching for relevant documents...")
        docs = get_search_results(question, top_k=5)

        if not docs:
            print("No relevant documents found.")
            continue

        print(f"Found {len(docs)} relevant document(s). Printing retrieved chunks:")
        for i, doc in enumerate(docs, 1):
            print(f"\n--- Chunk {i} ---\n{doc}")

        # ──────────────────────────────────────────────
        # STEP 3: Generate grounded answer
        # ──────────────────────────────────────────────
        print("\nGenerating answer...")
        answer = get_grounded_answer(question, docs, conversation_history)
        print(f"\nAssistant: {answer}")

        # ✅ Append this turn to history after a successful answer
        conversation_history.append({"role": "user", "content": question})
        conversation_history.append({"role": "assistant", "content": answer})



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")