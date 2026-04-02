import os
import sys
import json
import asyncio
import uuid
import re
from typing import Annotated
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
import requests

from agent_framework import tool
from agent_framework.openai import OpenAIChatCompletionClient
from tool_data import Tools
load_dotenv()

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

HISTORY_LIMIT = 12
KNOWLEDGE_TOP_K = 10
TICKETS_FILE = Path("tickets.jsonl")
POST_URL = "https://1121c538-16ba-44b5-a5c9-d5319443f585.mock.pstmn.io/post"

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

TOOL_REQUEST_SIGNALS = [
    "lookup user",
    "find user",
    "check device",
    "device status",
    "create ticket",
    "create a ticket",
    "open ticket",
    "open a ticket",
    "raise ticket",
    "raise a ticket",
    "escalate",
]

TICKET_REQUEST_SIGNALS = [
    "create ticket",
    "create a ticket",
    "open ticket",
    "open a ticket",
    "raise ticket",
    "raise a ticket",
    "escalate this",
    "escalate issue",
    "escalate",
]

TICKET_CONFIRMATION_SIGNALS = [
    "yes",
    "yes please",
    "please do",
    "go ahead",
    "do it",
    "proceed",
    "create one",
    "open one",
    "raise one",
    "sure",
    "okay",
    "ok",
]

FOLLOWUP_FAILURE_SIGNALS = [
    "still not working",
    "did not work",
    "didn't work",
    "no luck",
    "same issue",
    "still failing",
    "still locked out",
    "not resolved",
    "doesn't work",
    "cannot connect",
]

MAF_TRIAGE_INSTRUCTIONS = (
    "You are an IT Helpdesk triage agent.\n\n"
    "Your job is to read the user's request and conversation history, classify the issue, "
    "detect urgency, and decide which downstream agent should handle it.\n\n"
    "Respond ONLY with valid JSON (no markdown, no explanation):\n"
    '{"route_to": "knowledge|action|clarify", "urgency": "low|medium|high|critical", '
    '"category": "VPN|Email|MFA|Device|Account|Software|Hardware|General", '
    '"clarifying_question": null, "summary": "one-sentence issue description"}\n\n'
    "Routing rules:\n"
    '"knowledge" → user needs troubleshooting steps or information '
    "(VPN error, email crash, MFA setup, password reset, etc.).\n"
    '"action"    → user wants an operational task: look up a user, check a device, '
    "create a ticket, or explicitly asks to escalate.\n"
    "For account lockout/password issues, prefer knowledge unless the user explicitly asks to create/open/raise a ticket.\n"
    '"clarify"   → query is too vague to route; set clarifying_question '
    "to a single targeted follow-up question.\n\n"
    "Urgency rules:\n"
    "- critical : full business outage or security incident, all users affected\n"
    "- high     : single user fully blocked, cannot perform their job\n"
    "- medium   : partial degradation, a workaround exists\n"
    "- low      : general how-to question, no active blocking issue\n\n"
    "A query is vague when it lacks the application, OS, error message, or symptoms.\n"
    "Vague examples : 'VPN not working', 'Help me', 'Outlook issue'\n"
    "Specific examples : 'Outlook crashes on Windows 11 when opening attachments', "
    "'VPN on Mac returns error 619'"
)

MAF_KNOWLEDGE_INSTRUCTIONS = (
    "You are an IT Helpdesk knowledge agent.\n\n"
    "The retrieved knowledge base documents are provided directly in the user message under RETRIEVED DOCUMENTS.\n\n"
    "Rules:\n"
    "1. Answer using ONLY the documents provided in the prompt. Do not use outside knowledge.\n"
    "2. If no relevant information is present in the documents, respond with exactly: "
       "'I do not know based on the knowledge base. Would you like me to connect to IT Support?'\n"
    "3. Format answers as numbered step-by-step troubleshooting instructions.\n"
    "4. Be concise and professional. No apologies or filler phrases.\n"
    "5. If the answer is partial or uncertain, clearly state that in your response."
)

MAF_ACTION_INSTRUCTIONS = (
    "You are an IT Helpdesk action agent.\n\n"
    "Rules:\n"
    "1. Use lookup_user only for user identity lookups.\n"
    "2. Use check_device_status only for device state checks.\n"
    "3. Use create_ticket when directed. All required fields will be provided — call the tool immediately with the given values.\n"
    "4. Do NOT ask for more information when ticket fields are already supplied in the prompt.\n"
    "5. After ticket creation, reply with ticket_id, severity, status, and assignment_group.\n"
    "6. Keep the final answer concise and professional."
)

if not all([
    SEARCH_ENDPOINT,
    SEARCH_KEY,
    SEARCH_INDEX,
    OPENAI_ENDPOINT,
    OPENAI_KEY,
    OPENAI_DEPLOYMENT,
]):
    print("Missing required environment variables. Please check your .env file.")
    sys.exit(1)

# ============================================================
# Clients
# ============================================================
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_KEY)
)

# Keep AzureOpenAI for your existing retrieval/generation layers
openai_client = AzureOpenAI(
    api_key=OPENAI_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=OPENAI_ENDPOINT
)



def _write_ticket(ticket_record):
    with TICKETS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(ticket_record) + "\n")

# ============================================================
# MAF TOOLS
# ============================================================
@tool(
    name="lookup_user",
    description="Look up a corporate user by username. Use when the user asks to find user information."
)
def lookup_user(
    username: Annotated[str, Field(description="Employee username, for example jdoe")]
) -> str:
    user = Tools.MOCK_USERS.get(username.lower())
    if not user:
        return f"No user found for username '{username}'."

    return (
        f"User found:\n"
        f"- Username: {user['username']}\n"
        f"- Name: {user['name']}\n"
        f"- Department: {user['department']}\n"
        f"- Email: {user['email']}\n"
        f"- Device ID: {user['device_id']}"
    )


@tool(
    name="check_device_status",
    description="Check the status of a company device by device ID. Use for laptop or device status requests."
)
def check_device_status(
    device_id: Annotated[str, Field(description="Device ID, for example LAPTOP-1001")]
) -> str:
    device = Tools.MOCK_DEVICES.get(device_id.upper())
    if not device:
        return f"No device found for device ID '{device_id}'."

    return (
        f"Device status:\n"
        f"- Device ID: {device['device_id']}\n"
        f"- Status: {device['status']}\n"
        f"- VPN Client: {device['vpn_client']}\n"
        f"- Last Seen: {device['last_seen']}"
    )


@tool(
    name="create_ticket",
    description="Create an IT support ticket when the issue is unresolved or the user asks to open a ticket."
)
def create_ticket(
    issue: Annotated[str, Field(description="The unresolved IT issue")],
    user: Annotated[str, Field(description="Username or identifier of the user")] = "unknown",
    category: Annotated[str, Field(description="Issue category such as VPN, Email, MFA, Device")] = "General",
    severity: Annotated[str, Field(description="Business impact severity: Low, Medium, High, Critical")] = "Medium",
    impacted_system: Annotated[str, Field(description="Impacted application or system")]= "Unknown",
) -> str:
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "ticket_id": ticket_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Open",
        "assignment_group": "IT Service Desk",
        "user": user,
        "issue": issue,
        "category": category,
        "severity": severity,
        "impacted_system": impacted_system,
    }
    _write_ticket(record)

    # Post the ticket record to the external URL
    post_status = "Unknown"
    try:
        response = requests.post(POST_URL, json=record, timeout=5)
        post_status = f"Posted (HTTP {response.status_code})"
        if response.status_code != 200:
            print(f"[DEBUG] Failed to post ticket {ticket_id}: {response.text}")
    except Exception as e:
        print(f"[DEBUG] Error posting ticket {ticket_id}: {e}")
        post_status = f"Post failed: {str(e)}"

    return (
        f"Ticket created successfully.\n"
        f"- Ticket ID: {ticket_id}\n"
        f"- User: {user}\n"
        f"- Issue: {issue}\n"
        f"- Category: {category}\n"
        f"- Severity: {severity}\n"
        f"- Impacted System: {impacted_system}\n"
        f"- Status: Open\n"
        f"- Assignment Group: IT Service Desk\n"
        f"- External POST: {post_status}"
    )


@tool(
    name="search_knowledge_base",
    description=(
        "Search the IT knowledge base for troubleshooting steps and known solutions. "
        "Use a concise keyword query such as 'VPN error 619 Mac' or 'Outlook crash Windows 11'."
    )
)
def search_knowledge_base(
    query: Annotated[str, Field(description="Concise keyword search query describing the IT issue")]
) -> str:
    try:
        results = search_client.search(query, top=5)
        docs = []
        for doc in results:
            for field in ["content", "text", "chunk", "chunk_text"]:
                if field in doc and doc[field]:
                    docs.append(doc[field])
                    break
            else:
                docs.append(str(doc))
        if not docs:
            return "No relevant documents found in the knowledge base."
        return "\n\n---\n\n".join(docs)
    except Exception as e:
        return f"Knowledge base search failed: {e}"


# ============================================================
# MAF AGENTS
# ============================================================

triage_agent = OpenAIChatCompletionClient(
    model=OPENAI_DEPLOYMENT,
    azure_endpoint=OPENAI_ENDPOINT,
    api_version=OPENAI_API_VERSION,
    api_key=OPENAI_KEY,
).as_agent(
    name="TriageAgent",
    instructions=MAF_TRIAGE_INSTRUCTIONS,
    tools=[],
)

knowledge_agent = OpenAIChatCompletionClient(
    model=OPENAI_DEPLOYMENT,
    azure_endpoint=OPENAI_ENDPOINT,
    api_version=OPENAI_API_VERSION,
    api_key=OPENAI_KEY,
).as_agent(
    name="KnowledgeAgent",
    instructions=MAF_KNOWLEDGE_INSTRUCTIONS,
    tools=[],
)

action_agent = OpenAIChatCompletionClient(
    model=OPENAI_DEPLOYMENT,
    azure_endpoint=OPENAI_ENDPOINT,
    api_version=OPENAI_API_VERSION,
    api_key=OPENAI_KEY,
).as_agent(
    name="ActionAgent",
    instructions=MAF_ACTION_INSTRUCTIONS,
    tools=[lookup_user, check_device_status, create_ticket],
)

# ════════════════════════════════════════════════════
# LAYER 1 — RETRIEVAL QUERY BUILDER
# ════════════════════════════════════════════════════

def build_retrieval_query(user_input, conversation_history):
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


def extract_error_code(text):
    """Extract a numeric or hex-style error code from user text when present."""
    match = re.search(r"\b(?:error(?:\s+code)?\s*)?(0x[0-9A-Fa-f]+|\d{3,6})\b", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def docs_contain_error_code(docs, error_code):
    """Return True only when at least one retrieved document contains the exact error code."""
    if not error_code:
        return False
    return any(error_code in doc.lower() for doc in docs)

# ════════════════════════════════════════════════════
# LAYER 3 — TRIAGE (Clarification Check)
# ════════════════════════════════════════════════════

def is_query_vague(question, conversation_history):
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
    system_prompt = build_system_prompt(context_docs)

    messages = [
        {"role": "system", "content": system_prompt},
        *conversation_history[-HISTORY_LIMIT:],
        {"role": "user", "content": question}
    ]

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=0.2,
            max_tokens=768
        )
        answer = response.choices[0].message.content.strip()
        return answer
    except Exception as e:
        return f"Error from OpenAI: {e}"

# ════════════════════════════════════════════════════
# LAYER 5 — ESCALATION CHECK
# ════════════════════════════════════════════════════

def check_escalation(answer):
    answer_lower = answer.lower()

    keyword_hit = any(trigger in answer_lower for trigger in ESCALATION_TRIGGERS)
    if keyword_hit:
        print("[DEBUG] Escalation triggered by keyword match")
        return answer + ESCALATION_SUFFIX

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
        parsed = json.loads(raw)

        if parsed.get("uncertain", False):
            print("[DEBUG] Escalation triggered by LLM confidence check")
            return answer + ESCALATION_SUFFIX

    except Exception as e:
        print(f"[DEBUG] Escalation LLM check failed: {e} — skipping")

    return answer

# ════════════════════════════════════════════════════
# TOOL REQUEST DETECTION
# ════════════════════════════════════════════════════

def looks_like_tool_request(user_input):
    msg = user_input.lower()
    return any(signal in msg for signal in TOOL_REQUEST_SIGNALS)


def looks_like_ticket_request(user_input):
    msg = user_input.lower()
    return any(signal in msg for signal in TICKET_REQUEST_SIGNALS)


def looks_like_ticket_confirmation(user_input):
    msg = user_input.strip().lower()
    return any(msg == signal or msg.startswith(signal) for signal in TICKET_CONFIRMATION_SIGNALS)


def last_assistant_offered_escalation(conversation_history):
    """Return True if the most recent assistant message contained the escalation suffix."""
    for message in reversed(conversation_history):
        if message.get("role") == "assistant":
            return ESCALATION_SUFFIX in message.get("content", "")
    return False


def should_run_escalation_check(response_text):
    """
    Run escalation logic only for explicit unknown-answer outcomes.
    This avoids escalating good KB-backed instructions.
    """
    response_lower = response_text.lower()
    return "i do not know based on the knowledge base" in response_lower


def user_reports_failed_steps(user_input, conversation_history):
    """
    Detect follow-up messages indicating that prior troubleshooting steps failed.
    """
    msg = user_input.lower()
    mentions_failure = any(signal in msg for signal in FOLLOWUP_FAILURE_SIGNALS)
    if not mentions_failure:
        return False

    for message in reversed(conversation_history):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        # Require prior step-based guidance and no existing escalation in that message.
        had_steps = "1." in content and "2." in content
        had_escalation = ESCALATION_SUFFIX in content
        return had_steps and not had_escalation

    return False


def extract_ticket_context(conversation_history):
    """
    Reads the full conversation and uses the LLM to extract structured ticket fields.
    Returns a dict with: issue, category, severity, impacted_system, user.
    """
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in conversation_history[-HISTORY_LIMIT:]
    )

    system_message = (
        "You are an IT ticket field extractor.\n\n"
        "Read the conversation below and extract the following fields for an IT support ticket.\n"
        "Be specific — use exact details mentioned in the conversation, not generic placeholders.\n\n"
        "Fields to extract:\n"
        "- issue: a one-sentence description of the IT problem (required)\n"
        "- category: one of VPN, Email, MFA, Device, Account, Hardware, Software, General\n"
        "- severity: one of Low, Medium, High, Critical — infer from impact described\n"
        "- impacted_system: the specific app, tool, or system affected\n"
        "- user: username or email if mentioned, otherwise 'unknown'\n\n"
        "Respond ONLY with valid JSON, no markdown, no explanation:\n"
        '{"issue": "...", "category": "...", "severity": "...", "impacted_system": "...", "user": "..."}'
    )

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": history_text},
            ],
            temperature=0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        print(f"[DEBUG] Extracted ticket context: {raw}")
        parsed = json.loads(raw)
        return {
            "issue": parsed.get("issue", "Unresolved IT issue"),
            "category": parsed.get("category", "General"),
            "severity": parsed.get("severity", "Medium"),
            "impacted_system": parsed.get("impacted_system", "Unknown"),
            "user": parsed.get("user", "unknown"),
        }
    except Exception as e:
        print(f"[DEBUG] Ticket context extraction failed: {e} — using defaults")
        return {
            "issue": "Unresolved IT issue from conversation",
            "category": "General",
            "severity": "Medium",
            "impacted_system": "Unknown",
            "user": "unknown",
        }


async def run_orchestrator(user_input: str, conversation_history: list) -> str:
    """
    MAF Orchestrator — receives every user request and routes it to the right agent:
      · TriageAgent    → classifies intent, urgency, and routing decision
      · KnowledgeAgent → searches the knowledge base and returns step-by-step answers
      · ActionAgent    → executes operational tasks (lookups, device checks, tickets)
    """
    print("\n[Orchestrator] Starting triage...")

    history_context = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in conversation_history[-HISTORY_LIMIT:]
    )
    triage_prompt = (
        f"Conversation so far:\n{history_context}\n\nLatest message: {user_input}"
        if history_context else user_input
    )

    # ── Step 1: Triage ──────────────────────────────────────────
    try:
        triage_response = await triage_agent.run(triage_prompt)
        triage_raw = triage_response.text.strip()
        print(f"[Orchestrator] Triage: {triage_raw}")
        triage_data = json.loads(triage_raw)
    except Exception as e:
        print(f"[Orchestrator] Triage failed: {e} — defaulting to knowledge route")
        triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}

    route_to = triage_data.get("route_to", "knowledge")
    urgency  = triage_data.get("urgency", "medium")
    category = triage_data.get("category", "General")

    # Safety gate: only allow direct action routing when user intent is explicitly operational.
    explicit_action_intent = looks_like_tool_request(user_input) or looks_like_ticket_request(user_input)
    if route_to == "action" and not explicit_action_intent:
        print("[Orchestrator] Action route overridden to KNOWLEDGE (no explicit action intent)")
        route_to = "knowledge"

    print(f"[Orchestrator] Route → {route_to.upper()} | Urgency: {urgency} | Category: {category}")

    # ── Step 2: Clarification ────────────────────────────────────
    if route_to == "clarify":
        return triage_data.get(
            "clarifying_question",
            "Could you provide more details about the issue?"
        )

    # ── Step 3a: Knowledge Agent ─────────────────────────────────
    if route_to == "knowledge":
        print("[Orchestrator] Dispatching → KnowledgeAgent")

        # Deterministic retrieval: enrich query with history, then fetch docs from Azure Search
        enriched_query = build_retrieval_query(user_input, conversation_history)
        docs = get_search_results(enriched_query, top_k=KNOWLEDGE_TOP_K)

        # Error-code-aware fallback: force retrieval anchored on the specific error code
        # if the first pass did not return matching chunks.
        error_code = extract_error_code(user_input)
        if error_code and docs and not docs_contain_error_code(docs, error_code):
            fallback_query = f"error code {error_code} {user_input}"
            print(f"[Orchestrator] Retrying retrieval with error-code fallback query: '{fallback_query}'")
            fallback_docs = get_search_results(fallback_query, top_k=KNOWLEDGE_TOP_K)
            if fallback_docs:
                docs = fallback_docs

        if error_code and not docs_contain_error_code(docs, error_code):
            print(f"[Orchestrator] Error code {error_code} not found in retrieved docs — treating as KB miss")
            return (
                "I do not know based on the knowledge base. "
                "Would you like me to connect to IT Support?"
            )

        if not docs:
            print("[Orchestrator] No docs found — skipping KnowledgeAgent")
            return (
                "I do not know based on the knowledge base. "
                "Would you like me to connect to IT Support?"
            )

        numbered_docs = "\n\n".join(
            f"[Document {i}]\n{doc.strip()}" for i, doc in enumerate(docs, 1)
        )
        knowledge_prompt = (
            f"{f'Conversation history:{chr(10)}{history_context}{chr(10)}{chr(10)}' if history_context else ''}"
            f"User question: {user_input}\n\n"
            f"RETRIEVED DOCUMENTS:\n{numbered_docs}"
        )
        print(f"[Orchestrator] Passing {len(docs)} doc(s) to KnowledgeAgent")
        try:
            knowledge_response = await knowledge_agent.run(knowledge_prompt)
            return knowledge_response.text.strip()
        except Exception as e:
            return f"Knowledge base lookup failed: {e}"

    # ── Step 3b: Action Agent ─────────────────────────────────────
    if route_to == "action":
        print("[Orchestrator] Dispatching → ActionAgent")
        try:
            action_response = await action_agent.run(user_input)
            return action_response.text.strip()
        except Exception as e:
            return f"Action execution failed: {e}"

    return "I was unable to process your request. Please try again."

# ════════════════════════════════════════════════════
# LAYER 6 — AGENT CONTROLLER
# ════════════════════════════════════════════════════

def build_ticket_prompt(ctx):
    """Build an explicit tool-call prompt from extracted ticket context."""
    return (
        f"Create an IT support ticket with the following details:\n"
        f"- user: {ctx['user']}\n"
        f"- issue: {ctx['issue']}\n"
        f"- category: {ctx['category']}\n"
        f"- severity: {ctx['severity']}\n"
        f"- impacted_system: {ctx['impacted_system']}\n"
        "Call create_ticket now with these exact values."
    )


async def handle_user_message(user_input, conversation_history):
    print("\n[Agent Controller] Evaluating message...")

    # Pre-check: ticket confirmation following a prior escalation offer
    is_confirmation = (
        looks_like_ticket_confirmation(user_input)
        and last_assistant_offered_escalation(conversation_history)
    )
    if is_confirmation:
        print("[Agent Controller] Decision → TICKET CONFIRMATION → ActionAgent")
        ctx = extract_ticket_context(conversation_history)
        tool_prompt = build_ticket_prompt(ctx)
        print(f"[DEBUG] Ticket prompt sent to agent: {tool_prompt}")
        action_response = await action_agent.run(tool_prompt)
        return action_response.text, True

    # If user says previously provided steps failed, proactively offer escalation.
    if user_reports_failed_steps(user_input, conversation_history):
        print("[Agent Controller] Decision → FOLLOW-UP FAILURE → OFFER ESCALATION")
        return (
            "Thanks for trying those steps."
            + ESCALATION_SUFFIX
            + "\n\nWould you like me to create a support ticket for this issue?"
        ), True

    # Delegate all routing decisions to the MAF Orchestrator
    response = await run_orchestrator(user_input, conversation_history)
    if should_run_escalation_check(response):
        final_response = check_escalation(response)
    else:
        final_response = response

    if ESCALATION_SUFFIX in final_response:
        final_response += "\n\nWould you like me to create a support ticket for this issue?"

    return final_response, True

# ════════════════════════════════════════════════════
# MAIN LOOP
# ════════════════════════════════════════════════════

async def main():
    print("═" * 76)
    print("  Azure RAG IT Support Agent + Microsoft Agent Framework")
    print("  Memory ✓  Clarification ✓  Multi-Turn ✓  Escalation ✓  Orchestrator ✓")
    print("  Agents: TriageAgent · KnowledgeAgent · ActionAgent")
    print("═" * 76)
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

        response, should_store = await handle_user_message(user_input, conversation_history)

        print(f"\nAssistant: {response}")

        if should_store:
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")