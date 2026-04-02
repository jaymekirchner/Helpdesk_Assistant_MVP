import os
import sys
import json
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
import yaml

load_dotenv()

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

HISTORY_LIMIT = 12

# ✅ Phrases that signal the model is uncertain or lacks information
ESCALATION_TRIGGERS = [
    "i don't know based on the knowledge base",
    "i'm not sure",
    "i cannot find",
    "i could not find",
    "not found in the",
    "no information",
    "unable to find",
    "doesn't appear to be covered",
    "does not appear to be covered",
    "may need to",
    "you might want to contact",
    "it's possible that",
    "i'm unable to",
    "i am unable to",
    "unclear",
    "not certain",
]

ESCALATION_SUFFIX = "\n\n⚠️ Please contact IT support if the issue persists."

if not all([SEARCH_ENDPOINT, SEARCH_KEY, SEARCH_INDEX, OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT]):
    # add print statement to know which variables are missing
    missing_vars = [var for var, value in {
        "AZURE_SEARCH_ENDPOINT": SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY": SEARCH_KEY,
        "AZURE_SEARCH_INDEX": SEARCH_INDEX,
        "AZURE_OPENAI_ENDPOINT": OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY": OPENAI_KEY,
        "AZURE_OPENAI_DEPLOYMENT": OPENAI_DEPLOYMENT
    }.items() if not value]
    print(f"Missing required environment variables: {', '.join(missing_vars)}. Please check your .env file.")
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
# LAYER 1 — RETRIEVAL QUERY BUILDER
# ════════════════════════════════════════════════════

def build_retrieval_query(user_input, conversation_history):
    """
    Synthesizes conversation history + current input into one
    enriched retrieval query for better search relevance.
    Falls back to raw user_input if synthesis fails.
    """
    if not conversation_history:
        print(f"[DEBUG] No history — using raw query: {user_input}")
        return user_input

    system_message = (
        "You are a search query builder for an IT support assistant.\n\n"
        "Your job is to thoroughly read the conversation history and the latest user message, "
        "then produce a single, concise search query that captures the FULL intent "
        "of the conversation — not just the latest message.\n\n"
        "Rules:\n"
        "1. Combine relevant details from the chat history and the latest message.\n"
        "2. Output ONLY the search query string. No explanation, no punctuation, "
           "no JSON, no markdown.\n"
        "3. Keep it under 30 words.\n"
        "4. Use keywords, not full sentences.\n\n"
        "Examples:\n" # ✅ examples to guide the model towards keyword-based queries that combine history + latest input
        "  History: 'VPN not working' / Assistant asked about OS / User said 'Windows'\n"
        "  Output : VPN not working Windows\n\n"
        "  History: 'Outlook keeps crashing' / Assistant asked about error / "
        "User said 'error 0x800CCC0E'\n"
        "  Output : Outlook crashing error 0x800CCC0E\n\n"
    )

    messages = [
        {"role": "system", "content": system_message},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": user_input}
    ]

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0,
            max_tokens=50
        )
        enriched_query = response.choices[0].message.content.strip()
        print(f"[DEBUG] Enriched retrieval query: '{enriched_query}'")
        return enriched_query
    except Exception as e:
        print(f"[DEBUG] Query enrichment failed: {e} — falling back to raw input")
        return user_input


# ════════════════════════════════════════════════════
# LAYER 2 — RETRIEVAL
# ════════════════════════════════════════════════════

def get_search_results(query, top_k=5):
    """Query Azure AI Search with the enriched query and return top_k chunks."""
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
# LAYER 3 — TRIAGE (Clarification Check)
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
        "Examples of specific: 'Outlook crashes on Windows 11 when opening attachments', 'VPN on MacOS with Certification Validation Error' "
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
        return False, None


# ════════════════════════════════════════════════════
# LAYER 4 — GENERATION
# ════════════════════════════════════════════════════

def build_system_prompt(context_docs):
    """
    Builds the system prompt with numbered retrieved documents
    and strict enterprise prompt rules.
    """
    numbered_docs = "\n\n".join(
        f"[Document {i}]\n{doc.strip()}"
        for i, doc in enumerate(context_docs, 1)
    )

    return (
        "You are a professional IT helpdesk support assistant for an enterprise environment.\n\n"

        "RULES — follow these exactly, without exception:\n"
        "1. Answer using ONLY the retrieved documents provided below. "
           "Do not use ANY outside knowledge.\n"
        "2. If the answer cannot be found in the documents, respond with EXACTLY: "
           "'I do not know based on the knowledge base. Would you like me to connect to IT Support?' Do not guess or infer.\n"
        "3. Always return your answer as step-by-step troubleshooting instructions "
           "using a numbered list. Each step must be a single, clear action.\n"
        "4. Be concise and professional. Avoid filler phrases, apologies, or preamble. "
           "Get straight to the steps.\n"
        "5. If the conversation history shows a previous clarification exchange, "
           "factor that context into your answer.\n"
        "6. If you are uncertain about any step or the answer is only partially covered "
           "by the documents, clearly state your uncertainty in the response.\n\n"

        "RETRIEVED DOCUMENTS:\n"
        f"{numbered_docs}\n\n"

        "Remember: base your answer solely on the documents above. "
        "If the information is not there, say: 'I do not know based on my knowledge base. Would you like me to connect to IT Support?'"
    )


def get_grounded_answer(question, context_docs, conversation_history):
    """
    Sends to the model:
      [1] System prompt  — rules + retrieved documents (numbered)
      [2] Recent history — last HISTORY_LIMIT messages
      [3] User question  — current turn
    """
    system_prompt = build_system_prompt(context_docs)

    messages = [
        {"role": "system", "content": system_prompt},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": question}
    ]

    try:
        print(f"[DEBUG] Calling deployment : {OPENAI_DEPLOYMENT}")
        print(f"[DEBUG] Documents in prompt: {len(context_docs)}")
        print(f"[DEBUG] History messages   : {min(len(conversation_history), HISTORY_LIMIT)}")
        print(f"[DEBUG] Total messages sent: {len(messages)}")

        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.2,
            max_tokens=768
        )
        answer = response.choices[0].message.content.strip()
        print(f"[DEBUG] Response length    : {len(answer)} chars")
        return answer
    except Exception as e:
        return f"Error from OpenAI: {e}"


# ════════════════════════════════════════════════════
# LAYER 5 — ESCALATION CHECK  ← new
# ════════════════════════════════════════════════════

def check_escalation(answer):
    """
    Scans the answer for uncertainty signals and appends the
    escalation suffix if any trigger phrase is detected.

    Two-pass approach:
      Pass 1 — keyword scan (fast, zero LLM cost)
      Pass 2 — LLM confidence check (catches subtler uncertainty
                that keywords would miss)

    Returns the final answer string, escalated if needed.
    """
    answer_lower = answer.lower()

    # ── Pass 1: Fast keyword scan ──────────────────────────────────────
    keyword_hit = any(trigger in answer_lower for trigger in ESCALATION_TRIGGERS)

    if keyword_hit:
        print("[DEBUG] Escalation triggered by keyword match")
        return answer + ESCALATION_SUFFIX

    # ── Pass 2: LLM confidence check ───────────────────────────────────
    # ✅ Catches uncertainty expressed naturally without trigger keywords,
    #    e.g. "This may resolve the issue" or "Results could vary"
    system_message = (
        "You are an escalation detector for an IT support assistant.\n\n"
        "Read the assistant's answer below and decide if it expresses "
        "any uncertainty, partial knowledge, or lack of confidence.\n\n"
        "Signals of uncertainty include:\n"
        "- Hedging language (may, might, could, possibly, perhaps)\n"
        "- Partial answers or gaps ('this might help but...')\n"
        "- Suggestions to try something without confidence it will work\n"
        "- Any implication the answer is incomplete\n\n"
        "Respond ONLY with JSON:\n"
        '{"uncertain": true}  or  {"uncertain": false}\n\n'
        "No explanation. No markdown. JSON only."
    )

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": answer}
            ],
            temperature=0,
            max_tokens=20
        )
        raw = response.choices[0].message.content.strip()
        print(f"[DEBUG] Escalation LLM check: {raw}")
        parsed = json.loads(raw)

        if parsed.get("uncertain", False):
            print("[DEBUG] Escalation triggered by LLM confidence check")
            return answer + ESCALATION_SUFFIX

    except Exception as e:
        print(f"[DEBUG] Escalation LLM check failed: {e} — skipping")

    print("[DEBUG] No escalation needed")
    return answer  # ✅ return unchanged if confident


# ════════════════════════════════════════════════════
# LAYER 6 — AGENT CONTROLLER (the brain)
# ════════════════════════════════════════════════════

def handle_user_message(user_input, conversation_history):
    """
    The Agent Controller — single entry point for every user message.

    Decision flow:
        1. Is the query vague?       → clarify
        2. Build enriched query      → combine history + input
        3. Retrieve documents        → search knowledge base
        4. Generate grounded answer  → LLM with rules + docs + history
        5. Check for escalation      → append IT support note if uncertain
    """
    print("\n[Agent Controller] Evaluating message...")

    # ── Step 1: Clarification check ────────────────────────────────────
    is_vague, clarifying_question = is_query_vague(user_input, conversation_history)

    if is_vague and clarifying_question:
        print("[Agent Controller] Decision → CLARIFY")
        return clarifying_question, True

    print("[Agent Controller] Decision → RETRIEVE + ANSWER")

    # ── Step 2: Build enriched retrieval query ──────────────────────────
    enriched_query = build_retrieval_query(user_input, conversation_history)

    # ── Step 3: Retrieve documents ──────────────────────────────────────
    docs = get_search_results(enriched_query, top_k=5)

    if not docs:
        # ✅ No docs = immediate escalation, no LLM call needed
        return (
            "I don't know based on the knowledge base."
            + ESCALATION_SUFFIX
        ), True

    # print(f"\nRetrieved {len(docs)} chunk(s):")
    # for i, doc in enumerate(docs, 1):
    #     print(f"\n--- Document {i} ---\n{doc}")

    # ── Step 4: Generate grounded answer ───────────────────────────────
    answer = get_grounded_answer(user_input, docs, conversation_history)

    # ── Step 5: Escalation check ────────────────────────────────────────
    final_answer = check_escalation(answer)

    return final_answer, True


# ════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════

def main():
    print("═" * 62)
    print("  Azure RAG IT Support Agent")
    print("  Memory ✓  Clarification ✓  Controller ✓  Multi-Turn ✓  Escalation ✓")
    print("═" * 62)
    print("Commands: 'exit' to quit · 'reset' to clear history\n")
    print("\nHello I am an IT helpdesk support assistant. \n\nHow can I help you today?\n")

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

        response, should_store = handle_user_message(user_input, conversation_history)

        print(f"\nAssistant: {response}")

        if should_store:
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
