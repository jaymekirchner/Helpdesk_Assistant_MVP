# Signals that indicate the user is reporting a failed troubleshooting step
FOLLOWUP_FAILURE_SIGNALS = [
    "still not working",
    "didn't help",
    "no change",
    "problem persists",
    "issue persists",
    "not fixed",
    "didn't solve",
    "did not solve",
    "same issue",
    "nothing changed",
    "doesn't work",
    "does not work",
    "not resolved",
    "keeps happening",
    "again",
    "tried everything",
    "followed steps but",
    "all steps but",
    "no luck",
    "failed again"
]
import re
import os
import sys
import json
import asyncio
import time
from typing import Annotated
from dotenv import load_dotenv
from pydantic import Field
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
try:
    from agent_framework import tool
except Exception:
    # Fallback for older/incompatible agent_framework builds that do not expose `tool`.
    def tool(*_args, **_kwargs):
        def _decorator(func):
            return func
        return _decorator

    print(
        "[Startup Warning] agent_framework.tool unavailable; using no-op tool decorator.",
        file=sys.stderr,
    )

try:
    from agent_framework.openai import OpenAIChatCompletionClient
except Exception as e:
    OpenAIChatCompletionClient = None
    print(
        f"[Startup Warning] agent_framework.openai unavailable: {e}",
        file=sys.stderr,
    )

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
    "escalate"
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
    "escalate"
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
    "yes thanks",
    "yes thank you",
    "please create a ticket",
    "please open a ticket",
    "please raise a ticket",
    "please do create a ticket",
    "please do open a ticket",
    "please do raise a ticket"
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
    "1. Use lookup_user strictly for user identity lookup (this includes retrieving user profile and associated device_id).\n"
    "2. Use check_device_status only for device state checks.\n"
    "3. Use create_ticket when directed.\n"
    "4. Before creating a ticket, make sure you have:\n"
    " - first name\n"
    " - last name\n"
    " - issue description\n"
    "5. If first name or last name is missing, ask for them separately:\n"
    " - First ask for the first name\n"
    " - Then ask for the last name\n"
    "6. After collecting the name, call lookup_user to retrieve user identity and associated device_id.\n"
    "7. Include the user's full name and device_id in the ticket payload whenever available.\n"
    "8. Do NOT ask for more information if all required ticket fields are already available.\n"
    "9. After ticket creation, reply with ticket_id, severity, status, and assignment_group.\n"
    "10. Keep the final answer concise and professional."
)

_MISSING_STARTUP_VARS = [
    name for name, value in {
        "AZURE_SEARCH_ENDPOINT": SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY": SEARCH_KEY,
        "AZURE_SEARCH_INDEX": SEARCH_INDEX,
        "AZURE_OPENAI_ENDPOINT": OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY": OPENAI_KEY,
        "AZURE_OPENAI_DEPLOYMENT": OPENAI_DEPLOYMENT,
    }.items()
    if not value
]

if _MISSING_STARTUP_VARS:
    print(
        "[Startup Warning] Missing environment variables: "
        + ", ".join(_MISSING_STARTUP_VARS)
        + ". App will start in degraded mode."
    )

# ============================================================
# Clients
# ============================================================
search_client = None
if SEARCH_ENDPOINT and SEARCH_KEY and SEARCH_INDEX:
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX,
        credential=AzureKeyCredential(SEARCH_KEY)
    )

# Keep AzureOpenAI for your existing retrieval/generation layers
openai_client = None
if OPENAI_ENDPOINT and OPENAI_KEY and OPENAI_DEPLOYMENT:
    openai_client = AzureOpenAI(
        api_key=OPENAI_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=OPENAI_ENDPOINT
    )

_MCP_MAX_RETRIES = 3
_MCP_RETRY_BACKOFF = [0.5, 1.5, 3.0]  # seconds between attempts
_MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")


def _call_mcp_tool(tool_name: str, args: dict):
    """Call an MCP tool over HTTP transport with retry/backoff on transient errors."""
    from fastmcp import Client
    import concurrent.futures

    async def _call_async():
        client = Client(_MCP_SERVER_URL)
        async with client:
            return await client.call_tool(tool_name, args)

    last_exc = None
    for attempt in range(_MCP_MAX_RETRIES):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call_async()).result()
        except Exception as e:
            last_exc = e
            if attempt < _MCP_MAX_RETRIES - 1:
                delay = _MCP_RETRY_BACKOFF[attempt]
                print(f"[MCP] Tool '{tool_name}' attempt {attempt + 1} failed: {e} — retrying in {delay}s")
                time.sleep(delay)
            else:
                print(f"[MCP] Tool '{tool_name}' failed after {_MCP_MAX_RETRIES} attempts: {e}")
    raise last_exc


def _extract_mcp_records(result):
    """Normalize MCP CallToolResult content into parsed record dicts."""
    records = []
    content_items = getattr(result, "content", None) or [result]
    for item in content_items:
        text = getattr(item, "text", None) or str(item)
        try:
            records.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            records.append({"raw": text})
    return records

# ============================================================
# MAF TOOLS
# ============================================================
@tool(
    name="lookup_user",
    description="Look up a corporate user by username. Use when the user asks to find user information."
)
def lookup_user(
    username: Annotated[str, Field(description="Employee username, for example john.doe")]
) -> str:
    try:
        result = _call_mcp_tool("lookup_user", {"username": username})
        records = _extract_mcp_records(result)
        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return envelope.get("error") or "User lookup failed."
        record = envelope.get("data") or {}
        full_name = " ".join(filter(None, [record.get("first_name"), record.get("last_name")])).strip()
        if not full_name:
            full_name = record.get("name", "Unknown")
        return (
            "User found:\n"
            f"- Username: {record.get('username', username)}\n"
            f"- Name: {full_name}\n"
            f"- Department: {record.get('department', 'Unknown')}\n"
            f"- Email: {record.get('email', 'Unknown')}\n"
            f"- Device ID: {record.get('device_id', 'Unknown')}"
        )
    except Exception as e:
        return f"Error looking up user via MCP: {str(e)}"


@tool(
    name="check_device_status",
    description="Check the status of a company device by device ID or username. Use for laptop or device status requests."
)
def check_device_status(
    device_or_username: Annotated[str, Field(description="Device ID (for example LAPTOP-1001) or username (for example john.doe)")]
) -> str:
    try:
        result = _call_mcp_tool("check_device_status", {"device_or_username": device_or_username})
        records = _extract_mcp_records(result)
        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return envelope.get("error") or "Device lookup failed."
        record = envelope.get("data") or {}
        return (
            "Device status:\n\n"
            "Match 1:\n"
            f"- Device ID: {record.get('device_id', 'Unknown')}\n"
            f"- Username: {record.get('username', 'unknown')}\n"
            f"- Status: {record.get('status', 'Unknown')}\n"
            f"- VPN Client: {record.get('vpn_client', 'Unknown')}\n"
            f"- Last Seen: {record.get('last_seen', 'Unknown')}"
        )
    except Exception as e:
        return f"Error checking device status via MCP: {str(e)}"


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
    """Create a ticket via MCP server tool."""
    try:
        result = _call_mcp_tool(
            "create_ticket",
            {
                "issue": issue,
                "user": user,
                "category": category,
                "severity": severity,
                "impacted_system": impacted_system,
            },
        )
        records = _extract_mcp_records(result)

        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return f"Ticket creation failed: {envelope.get('error') or 'Unknown error'}"
        data = envelope.get("data") or {}
        return (
            f"Ticket created successfully. "
            f"ID: {data.get('ticket_id')}, "
            f"Status: {data.get('status')}, "
            f"Priority: {data.get('priority')}, "
            f"Assignment Group: {data.get('assignment_group')}"
        )
    except Exception as e:
        return f"Error calling MCP ticket tool: {e}"


# ============================================================
# MAF AGENTS
# ============================================================

triage_agent = None
knowledge_agent = None
action_agent = None
if OPENAI_ENDPOINT and OPENAI_KEY and OPENAI_DEPLOYMENT and OpenAIChatCompletionClient is not None:
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
    if triage_agent is None:
        print("[Orchestrator] Triage agent unavailable — defaulting to knowledge route")
        triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}
    else:
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

    # Force route_to 'action' if user input matches a ticket request
    if looks_like_ticket_request(user_input):
        print("[Orchestrator] Overriding route to ACTION due to explicit ticket request.")
        route_to = "action"

    # Safety note: triage can infer operational intent from full context,
    # so do not force-downgrade ACTION based only on keyword matching.
    explicit_action_intent = looks_like_tool_request(user_input) or looks_like_ticket_request(user_input)
    if route_to == "action" and not explicit_action_intent:
        print("[Orchestrator] Action route kept from TRIAGE (weak explicit signal, context-based action intent)")

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
        if knowledge_agent is None:
            return (
                "Knowledge agent is unavailable because backend AI components failed to initialize. "
                "Please check app settings and startup logs."
            )

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
        if action_agent is None:
            return "Action agent is unavailable because Azure OpenAI settings are missing or invalid."
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
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        ctx = extract_ticket_context(conversation_history)
        tool_prompt = build_ticket_prompt(ctx)
        print(f"[DEBUG] Ticket prompt sent to agent: {tool_prompt}")
        action_response = await action_agent.run(tool_prompt)
        return action_response.text, True

    # NEW: If last assistant message was a ticket field request, parse user reply and create ticket
    if conversation_history:
        last_msg = conversation_history[-1]
        if last_msg.get("role") == "assistant" and "required fields to create the ticket" in last_msg.get("content", ""):
            # Try to parse user input as comma-separated fields: issue, user, severity (optionally category, impacted_system)
            parts = [p.strip() for p in user_input.split(",")]
            # Set defaults
            issue = parts[0] if len(parts) > 0 else "Unspecified issue"
            user = parts[1] if len(parts) > 1 else "unknown"
            severity = parts[2] if len(parts) > 2 else "Medium"
            category = parts[3] if len(parts) > 3 else "General"
            impacted_system = parts[4] if len(parts) > 4 else "Unknown"
            ticket_prompt = (
                f"Create an IT support ticket with the following details:\n"
                f"- user: {user}\n"
                f"- issue: {issue}\n"
                f"- category: {category}\n"
                f"- severity: {severity}\n"
                f"- impacted_system: {impacted_system}\n"
                "Call create_ticket now with these exact values."
            )
            print(f"[Agent Controller] Auto-creating ticket from user reply: {ticket_prompt}")
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            action_response = await action_agent.run(ticket_prompt)
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