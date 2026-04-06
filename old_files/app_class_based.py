# app_class_based.py
#
# Class-based refactor of appFinal.py
# All original logic is preserved; the code is reorganized into eight cohesive classes:
#
#   Config              — constants, signals, prompts, env keys
#   MCPClient           — HTTP MCP transport helpers (call, extract, format)
#   ToolRegistry        — @tool-decorated callable functions for MAF agents
#   AgentFactory        — creates and holds TriageAgent, KnowledgeAgent, ActionAgent
#   RetrievalEngine     — Azure AI Search query builder + retrieval helpers
#   EscalationService   — keyword + LLM escalation check
#   ConversationDetector— all looks_like_*, last_assistant_*, extract_*, get_* helpers
#   Orchestrator        — triage → knowledge/action MAF routing pipeline
#   AgentController     — top-level conversation controller (handle_user_message)
#
# Entry point: async main() wires all classes together and runs the chat loop.

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


# ════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════

class Config:
    """All application constants, signals, prompts, and environment settings."""

    # Tuning
    HISTORY_LIMIT = 12
    KNOWLEDGE_TOP_K = 10

    # MCP
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")
    MCP_MAX_RETRIES = 3
    MCP_RETRY_BACKOFF = [0.5, 1.5, 3.0]

    # Azure credentials
    SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
    SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
    SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
    OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    # ── Signals ──────────────────────────────────────────────────────────────

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
        "failed again",
    ]

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
        "lookup ticket",
        "look up ticket",
        "ticket status",
        "ticket details",
        "check ticket",
        "escalate",
    ]

    TICKET_LOOKUP_SIGNALS = [
        "lookup ticket",
        "look up ticket",
        "lookup tickets",
        "look up tickets",
        "ticket status",
        "ticket details",
        "check ticket",
        "ticket info",
        "ticket information",
        "find ticket",
        "find tickets",
        "search ticket",
        "search tickets",
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
        "yes thanks",
        "yes thank you",
        "please create a ticket",
        "please open a ticket",
        "please raise a ticket",
        "please do create a ticket",
        "please do open a ticket",
        "please do raise a ticket",
    ]

    # ── Escalation ────────────────────────────────────────────────────────────

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

    # ── Prompts ───────────────────────────────────────────────────────────────

    IDENTITY_LOOKUP_PROMPT = (
        "Thanks. Please provide either your username or your email so I can look up your account details."
    )
    LOOKUP_METHOD_PROMPT = (
        "Would you like to look up the user by username or by first and last name? "
        "Please reply with 'username' or 'name'."
    )
    LOOKUP_USERNAME_INPUT_PROMPT = "Please provide the username (for example, john.doe)."
    LOOKUP_FIRST_NAME_PROMPT = "Please provide the first name."
    LOOKUP_LAST_NAME_PROMPT = "Please provide the last name."
    LOOKUP_DISAMBIGUATE_PROMPT = (
        "Multiple users found. Please enter the match number of the user you'd like to proceed with "
        "(for example, reply with '1' for Match 1)."
    )
    LOOKUP_NEXT_ACTION_PROMPT = (
        "What would you like to do next? Reply with 'device' to check device details "
        "or 'ticket' to create a support ticket."
    )
    KB_TICKET_IDENTITY_METHOD_PROMPT = (
        "To open a support ticket I'll need to identify you. "
        "Would you like to provide your username or your email address? "
        "Please reply with 'username' or 'email'."
    )
    KB_TICKET_USERNAME_INPUT_PROMPT = "Please provide your username (for example, john.doe)."
    KB_TICKET_EMAIL_INPUT_PROMPT = "Please provide your email address."
    TICKET_LOOKUP_NUMBER_PROMPT = (
        "Please provide the ticket number you'd like to look up (for example, 12345)."
    )
    TICKET_LOOKUP_METHOD_PROMPT = (
        "Would you like to look up a ticket by ticket number, by username, or by user first and last name? "
        "Reply with 'number', 'username', or 'name'."
    )
    TICKET_LOOKUP_USER_PROMPT = (
        "Please provide the first name of the user to retrieve tickets for."
    )
    TICKET_LOOKUP_USER_LAST_NAME_PROMPT = (
        "Please provide the last name of the user to retrieve tickets for."
    )
    TICKET_LOOKUP_USERNAME_PROMPT = (
        "Please provide the username (for example, john.doe) to retrieve tickets for."
    )

    # ── MAF Agent Instructions ────────────────────────────────────────────────

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
        "'VPN on Mac returns error 619'\n\n"
        "Repeated input rule:\n"
        "If the latest user message is identical or near-identical to their immediately preceding message, "
        "and the assistant already responded to it, route to 'clarify' and set clarifying_question to: "
        "'It looks like you sent the same message again. Are you still waiting for something, "
        "or would you like to rephrase your request?'"
    )

    MAF_KNOWLEDGE_INSTRUCTIONS = (
        "You are an IT Helpdesk knowledge agent.\n\n"
        "Your ONLY source of information is the documentation retrieved from Azure AI Search "
        "and provided in the user message under RETRIEVED DOCUMENTS. "
        "You have no other knowledge source.\n\n"
        "Rules:\n"
        "1. Answer using ONLY the content of the RETRIEVED DOCUMENTS provided in the prompt.\n"
        "   - Do NOT use general knowledge, training data, or any information not present in those documents.\n"
        "   - Do NOT infer, assume, or extrapolate beyond what the documents explicitly state.\n"
        "2. If the RETRIEVED DOCUMENTS do not contain information relevant to the question, respond with exactly:\n"
        "   'I do not know based on the knowledge base. Would you like me to connect to IT Support?'\n"
        "3. Format answers as numbered step-by-step troubleshooting instructions.\n"
        "4. Be concise and professional. No apologies or filler phrases.\n"
        "5. If the documents provide only a partial answer, state clearly what is and is not covered."
    )

    MAF_ACTION_INSTRUCTIONS = (
        "You are an IT Helpdesk action agent.\n\n"
        "Rules:\n"
        "1. Use lookup_user to retrieve a user profile and their associated device_id.\n"
        "   - If you have the username, pass it as 'username'.\n"
        "   - If you only have the user's first and last name, pass them as 'first_name' and 'last_name' instead.\n"
        "   - Never pass both username and name fields at the same time.\n"
        "2. Use check_device_status only for device state checks.\n"
        "3. Use create_ticket only when explicitly directed by the user.\n"
        "4. Before creating a ticket, collect the following fields:\n"
        " - username OR first name + last name (to identify the user)\n"
        " - issue description\n"
        "5. ALWAYS scan the full conversation history first for these fields before asking the user:\n"
        "   - Look for a username in any prior message (e.g. 'john.doe', an email like 'john@corp.com').\n"
        "   - Look for a first name and last name mentioned anywhere in the conversation.\n"
        "   - Look for an issue description in the user's original request.\n"
        "   - If any field is found in history, use it directly — do NOT ask for it again.\n"
        "6. Only ask for a field if it is genuinely absent from the entire conversation history:\n"
        " - First ask for the first name\n"
        " - Then ask for the last name\n"
        "7. After confirming identity, call lookup_user to retrieve the device_id if not already known.\n"
        "8. Include the user's full name and device_id in the ticket payload whenever available.\n"
        "9. Do NOT ask for more information if all required ticket fields are already available.\n"
        "10. After ticket creation, reply with ticket_id, severity, status, and assignment_group.\n"
        "11. Keep the final answer concise and professional.\n"
        "12. When lookup_user returns multiple matches (more than one user found):\n"
        "    - Display all matches with their details.\n"
        "    - Ask the user: 'Please enter the match number of the user you'd like to proceed with "
        "(for example, reply with \\'1\\' for Match 1).'\n"
        "    - Do NOT automatically select a user, check a device, or create a ticket.\n"
        "    - Wait for the user to reply with a match number before taking any further action.\n"
        "13. After the user selects a match number:\n"
        "    - Display only the details for that specific match.\n"
        "    - Ask: 'What would you like to do next? Reply with \\'device\\' to check device details "
        "or \\'ticket\\' to create a support ticket.'\n"
        "    - Do NOT automatically proceed to check device status or create a ticket.\n"
        "    - Wait for the user's explicit choice before calling any further tools.\n"
        "14. Use lookup_ticket to retrieve details for an existing support ticket by its ticket ID.\n"
        "    - Display all returned fields: ticket_id, subject, status, severity, category, type,\n"
        "      assignment_group, created_at, and the associated user's first name, last name, and email.\n"
        "    - Do NOT ask for user identity or device details when looking up a ticket.\n"
        "    - If the ticket_id is not provided, ask: 'Please provide the ticket number you\\'d like to look up.'\n"
        "15. Use lookup_tickets_by_user to retrieve all tickets for a given user.\n"
        "    - Pass username if available, or first_name + last_name if the username is unknown.\n"
        "    - Display all returned tickets with their full details (ticket_id, subject, status, severity,\n"
        "      category, type, assignment_group, created_at, user name, and email).\n"
        "    - Do NOT ask for a specific ticket_id when the request is for all tickets for a user."
    )


# ════════════════════════════════════════════════════
# MCP CLIENT
# ════════════════════════════════════════════════════

class MCPClient:
    """Handles all communication with the FastMCP tool server over HTTP transport."""

    @staticmethod
    def call_tool(tool_name: str, args: dict):
        """Call a named MCP tool with automatic retry/backoff on transient failures."""
        from fastmcp import Client
        import concurrent.futures

        async def _call_async():
            client = Client(Config.MCP_SERVER_URL)
            async with client:
                return await client.call_tool(tool_name, args)

        last_exc = None
        for attempt in range(Config.MCP_MAX_RETRIES):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _call_async()).result()
            except Exception as e:
                last_exc = e
                if attempt < Config.MCP_MAX_RETRIES - 1:
                    delay = Config.MCP_RETRY_BACKOFF[attempt]
                    print(f"[MCP] Tool '{tool_name}' attempt {attempt + 1} failed: {e} — retrying in {delay}s")
                    time.sleep(delay)
                else:
                    print(f"[MCP] Tool '{tool_name}' failed after {Config.MCP_MAX_RETRIES} attempts: {e}")
        raise last_exc

    @staticmethod
    def extract_records(result) -> list:
        """Normalize a MCP CallToolResult into a list of parsed record dicts."""
        records = []
        content_items = getattr(result, "content", None) or [result]
        for item in content_items:
            text = getattr(item, "text", None) or str(item)
            try:
                records.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                records.append({"raw": text})
        return records

    @staticmethod
    def format_single_user(record: dict, fallback_username: str = "") -> str:
        """Format a single user record dict into a readable bullet list."""
        full_name = " ".join(filter(None, [record.get("first_name"), record.get("last_name")])).strip()
        if not full_name:
            full_name = record.get("name", "Unknown")
        return (
            f"- Username: {record.get('username', fallback_username)}\n"
            f"- Name: {full_name}\n"
            f"- Department: {record.get('department', 'Unknown')}\n"
            f"- Email: {record.get('email', 'Unknown')}\n"
            f"- Device ID: {record.get('device_id', 'Unknown')}"
        )


# ════════════════════════════════════════════════════
# TOOL REGISTRY
# ════════════════════════════════════════════════════

class ToolRegistry:
    """
    MAF tool functions registered with the @tool decorator.

    Each method is a @staticmethod so the underlying callable can be passed
    directly to as_agent(tools=[ToolRegistry.lookup_user, ...]).
    """

    @staticmethod
    @tool(
        name="lookup_user",
        description="Look up a corporate user by username OR by first and last name. Use when the user asks to find user information.",
    )
    def lookup_user(
        username: Annotated[str, Field(description="Employee username, for example john.doe. Leave empty if searching by name.")] = "",
        first_name: Annotated[str, Field(description="Employee first name. Use together with last_name when username is unknown.")] = "",
        last_name: Annotated[str, Field(description="Employee last name. Use together with first_name when username is unknown.")] = "",
    ) -> str:
        args: dict = {}
        if username:
            args["username"] = username
        elif first_name and last_name:
            args["first_name"] = first_name
            args["last_name"] = last_name
        else:
            return "Please provide either a username or both a first name and last name to look up a user."
        try:
            result = MCPClient.call_tool("lookup_user", args)
            records = MCPClient.extract_records(result)
            envelope = records[0] if records else {}
            if not isinstance(envelope, dict):
                return str(envelope)
            if not envelope.get("success"):
                return envelope.get("error") or "User lookup failed."
            data = envelope.get("data")
            if isinstance(data, list):
                count = envelope.get("count", len(data))
                if count == 1:
                    return "User found:\n" + MCPClient.format_single_user(data[0])
                lines = [f"{count} users found with that name:"]
                for i, record in enumerate(data, 1):
                    lines.append(f"\nMatch {i}:\n" + MCPClient.format_single_user(record))
                lines.append(f"\n{Config.LOOKUP_DISAMBIGUATE_PROMPT}")
                return "\n".join(lines)
            return "User found:\n" + MCPClient.format_single_user(data or {}, username)
        except Exception as e:
            return f"Error looking up user via MCP: {str(e)}"

    @staticmethod
    @tool(
        name="check_device_status",
        description="Check the status of a company device by device ID or username. Use for laptop or device status requests.",
    )
    def check_device_status(
        device_or_username: Annotated[str, Field(description="Device ID (for example LAPTOP-1001) or username (for example john.doe)")]
    ) -> str:
        try:
            result = MCPClient.call_tool("check_device_status", {"device_or_username": device_or_username})
            records = MCPClient.extract_records(result)
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

    @staticmethod
    @tool(
        name="lookup_ticket",
        description="Look up an existing support ticket by ticket ID. Returns status, category, subject, and the associated user's name and email.",
    )
    def lookup_ticket(
        ticket_id: Annotated[str, Field(description="The ticket ID or ticket number to look up")],
    ) -> str:
        try:
            result = MCPClient.call_tool("lookup_ticket", {"ticket_id": ticket_id})
            records = MCPClient.extract_records(result)
            envelope = records[0] if records else {}
            if not isinstance(envelope, dict):
                return str(envelope)
            if not envelope.get("success"):
                return envelope.get("error") or "Ticket lookup failed."
            data = envelope.get("data") or {}
            full_name = " ".join(filter(None, [data.get("first_name"), data.get("last_name")])).strip() or "Unknown"
            return (
                "Ticket details:\n"
                f"- Ticket ID: {data.get('ticket_id', 'Unknown')}\n"
                f"- Subject: {data.get('subject', 'Unknown')}\n"
                f"- Status: {data.get('status', 'Unknown')}\n"
                f"- Severity: {data.get('severity', 'Unknown')}\n"
                f"- Category: {data.get('category', 'Unknown')}\n"
                f"- Type: {data.get('ticket_type', 'Unknown')}\n"
                f"- Assignment Group: {data.get('assignment_group', 'Unknown')}\n"
                f"- Created At: {data.get('created_at', 'Unknown')}\n"
                f"- User: {full_name}\n"
                f"- Email: {data.get('email', 'Unknown')}"
            )
        except Exception as e:
            return f"Error looking up ticket via MCP: {str(e)}"

    @staticmethod
    @tool(
        name="lookup_tickets_by_user",
        description="Look up all support tickets for a specific user by username or first and last name.",
    )
    def lookup_tickets_by_user(
        username: Annotated[str, Field(description="Employee username, e.g. john.doe. Use when username is known.")] = "",
        first_name: Annotated[str, Field(description="Employee first name. Use with last_name when username is unknown.")] = "",
        last_name: Annotated[str, Field(description="Employee last name. Use with first_name when username is unknown.")] = "",
    ) -> str:
        try:
            result = MCPClient.call_tool(
                "lookup_tickets_by_user",
                {"username": username, "first_name": first_name, "last_name": last_name},
            )
            records = MCPClient.extract_records(result)
            envelope = records[0] if records else {}
            if not isinstance(envelope, dict):
                return str(envelope)
            if not envelope.get("success"):
                return envelope.get("error") or "Ticket lookup by user failed."
            tickets = envelope.get("data") or []
            if not tickets:
                return "No tickets found for that user."
            lines = [f"Found {len(tickets)} ticket(s):"]
            for i, t in enumerate(tickets, 1):
                full_name = " ".join(filter(None, [t.get("first_name"), t.get("last_name")])).strip() or "Unknown"
                lines.append(
                    f"\nTicket {i}:\n"
                    f"- Ticket ID: {t.get('ticket_id', 'Unknown')}\n"
                    f"- Subject: {t.get('subject', 'Unknown')}\n"
                    f"- Status: {t.get('status', 'Unknown')}\n"
                    f"- Severity: {t.get('severity', 'Unknown')}\n"
                    f"- Category: {t.get('category', 'Unknown')}\n"
                    f"- Type: {t.get('ticket_type', 'Unknown')}\n"
                    f"- Assignment Group: {t.get('assignment_group', 'Unknown')}\n"
                    f"- Created At: {t.get('created_at', 'Unknown')}\n"
                    f"- User: {full_name}\n"
                    f"- Email: {t.get('email', 'Unknown')}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Error looking up tickets by user via MCP: {str(e)}"

    @staticmethod
    @tool(
        name="create_ticket",
        description="Create an IT support ticket when the issue is unresolved or the user asks to open a ticket.",
    )
    def create_ticket(
        issue: Annotated[str, Field(description="The unresolved IT issue")],
        user: Annotated[str, Field(description="Username or identifier of the user")] = "unknown",
        category: Annotated[str, Field(description="Issue category such as VPN, Email, MFA, Device")] = "General",
        severity: Annotated[str, Field(description="Business impact severity: Low, Medium, High, Critical")] = "Medium",
        impacted_system: Annotated[str, Field(description="Impacted application or system")] = "Unknown",
    ) -> str:
        try:
            result = MCPClient.call_tool(
                "create_ticket",
                {
                    "issue": issue,
                    "user": user,
                    "category": category,
                    "severity": severity,
                    "impacted_system": impacted_system,
                },
            )
            records = MCPClient.extract_records(result)
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


# ════════════════════════════════════════════════════
# AGENT FACTORY
# ════════════════════════════════════════════════════

class AgentFactory:
    """
    Creates and holds the three MAF agents.

    Agents are None when required environment variables are missing;
    callers must guard with `if agent is not None`.
    """

    def __init__(self):
        self.triage_agent = None
        self.knowledge_agent = None
        self.action_agent = None
        self._validate_env()
        self._initialize_agents()

    def _validate_env(self):
        missing = [
            name
            for name, value in {
                "AZURE_SEARCH_ENDPOINT": Config.SEARCH_ENDPOINT,
                "AZURE_SEARCH_KEY": Config.SEARCH_KEY,
                "AZURE_SEARCH_INDEX": Config.SEARCH_INDEX,
                "AZURE_OPENAI_ENDPOINT": Config.OPENAI_ENDPOINT,
                "AZURE_OPENAI_API_KEY": Config.OPENAI_KEY,
                "AZURE_OPENAI_DEPLOYMENT": Config.OPENAI_DEPLOYMENT,
            }.items()
            if not value
        ]
        if missing:
            print(
                "[Startup Warning] Missing environment variables: "
                + ", ".join(missing)
                + ". App will start in degraded mode."
            )

    def _make_client(self):
        return OpenAIChatCompletionClient(
            model=Config.OPENAI_DEPLOYMENT,
            azure_endpoint=Config.OPENAI_ENDPOINT,
            api_version=Config.OPENAI_API_VERSION,
            api_key=Config.OPENAI_KEY,
        )

    def _initialize_agents(self):
        if not (
            Config.OPENAI_ENDPOINT
            and Config.OPENAI_KEY
            and Config.OPENAI_DEPLOYMENT
            and OpenAIChatCompletionClient is not None
        ):
            return

        self.triage_agent = self._make_client().as_agent(
            name="TriageAgent",
            instructions=Config.MAF_TRIAGE_INSTRUCTIONS,
            tools=[],
        )

        self.knowledge_agent = self._make_client().as_agent(
            name="KnowledgeAgent",
            instructions=Config.MAF_KNOWLEDGE_INSTRUCTIONS,
            tools=[],
        )

        self.action_agent = self._make_client().as_agent(
            name="ActionAgent",
            instructions=Config.MAF_ACTION_INSTRUCTIONS,
            tools=[
                ToolRegistry.lookup_user,
                ToolRegistry.check_device_status,
                ToolRegistry.create_ticket,
                ToolRegistry.lookup_ticket,
                ToolRegistry.lookup_tickets_by_user,
            ],
        )


# ════════════════════════════════════════════════════
# RETRIEVAL ENGINE
# ════════════════════════════════════════════════════

class RetrievalEngine:
    """Azure AI Search retrieval with OpenAI-powered query enrichment."""

    def __init__(self, openai_client, search_client):
        self.openai_client = openai_client
        self.search_client = search_client

    def build_retrieval_query(self, user_input: str, conversation_history: list) -> str:
        """Enrich the raw user query by combining it with relevant conversation history."""
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
            "Examples:\n"
            "  History: 'VPN not working' / Assistant asked about OS / User said 'Windows'\n"
            "  Output : VPN not working Windows\n\n"
            "  History: 'Outlook keeps crashing' / Assistant asked about error / "
            "User said 'error 0x800CCC0E'\n"
            "  Output : Outlook crashing error 0x800CCC0E\n\n"
        )

        messages = [
            {"role": "system", "content": system_message},
            *conversation_history[-Config.HISTORY_LIMIT:],
            {"role": "user", "content": user_input},
        ]

        try:
            response = self.openai_client.chat.completions.create(
                model=Config.OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=0,
                max_tokens=50,
            )
            enriched_query = response.choices[0].message.content.strip()
            print(f"[DEBUG] Enriched retrieval query: '{enriched_query}'")
            return enriched_query
        except Exception as e:
            print(f"[DEBUG] Query enrichment failed: {e} — falling back to raw input")
            return user_input

    def get_search_results(self, query: str, top_k: int = 5) -> list:
        """Run a full-text search and return the content of matching documents."""
        try:
            results = self.search_client.search(query, top=top_k)
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

    @staticmethod
    def extract_error_code(text: str):
        """Extract a numeric or hex error code from text, or return None."""
        match = re.search(
            r"\b(?:error(?:\s+code)?\s*)?(0x[0-9A-Fa-f]+|\d{3,6})\b",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).lower() if match else None

    @staticmethod
    def docs_contain_error_code(docs: list, error_code: str) -> bool:
        """Return True only when at least one document contains the exact error code."""
        if not error_code:
            return False
        return any(error_code in doc.lower() for doc in docs)


# ════════════════════════════════════════════════════
# ESCALATION SERVICE
# ════════════════════════════════════════════════════

class EscalationService:
    """Appends the escalation suffix when the agent's answer is uncertain or incomplete."""

    def __init__(self, openai_client):
        self.openai_client = openai_client

    @staticmethod
    def should_run_escalation_check(response_text: str) -> bool:
        """Only run the full escalation check for explicit KB-miss responses."""
        return "i do not know based on the knowledge base" in response_text.lower()

    def check_escalation(self, answer: str) -> str:
        """Append the escalation suffix if the answer triggers any uncertainty signal."""
        answer_lower = answer.lower()

        if any(trigger in answer_lower for trigger in Config.ESCALATION_TRIGGERS):
            print("[DEBUG] Escalation triggered by keyword match")
            return answer + Config.ESCALATION_SUFFIX

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
            response = self.openai_client.chat.completions.create(
                model=Config.OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": answer},
                ],
                temperature=0,
                max_tokens=20,
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)
            if parsed.get("uncertain", False):
                print("[DEBUG] Escalation triggered by LLM confidence check")
                return answer + Config.ESCALATION_SUFFIX
        except Exception as e:
            print(f"[DEBUG] Escalation LLM check failed: {e} — skipping")

        return answer


# ════════════════════════════════════════════════════
# CONVERSATION DETECTOR
# ════════════════════════════════════════════════════

class ConversationDetector:
    """
    All signal-detection and extraction helpers for conversation state management.

    Every method is a @staticmethod — no instance state is required.
    """

    # ── Input classification ──────────────────────────────────────────────────

    @staticmethod
    def looks_like_tool_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in Config.TOOL_REQUEST_SIGNALS)

    @staticmethod
    def looks_like_ticket_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in Config.TICKET_REQUEST_SIGNALS)

    @staticmethod
    def looks_like_ticket_confirmation(user_input: str) -> bool:
        msg = user_input.strip().lower()
        return any(msg == s or msg.startswith(s) for s in Config.TICKET_CONFIRMATION_SIGNALS)

    @staticmethod
    def looks_like_direct_lookup_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in ["lookup user", "look up user", "find a user", "user lookup"])

    @staticmethod
    def looks_like_ticket_lookup_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in Config.TICKET_LOOKUP_SIGNALS)

    # ── Conversation state probes ─────────────────────────────────────────────

    @staticmethod
    def last_assistant_offered_escalation(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") == "assistant":
                return Config.ESCALATION_SUFFIX in message.get("content", "")
        return False

    @staticmethod
    def last_assistant_requested_name_fields(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "first name" in content and "last name" in content
        return False

    @staticmethod
    def last_assistant_requested_identity_for_lookup(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "username or your email" in content or "username or email" in content
        return False

    @staticmethod
    def last_assistant_asked_lookup_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "reply with 'username' or 'name'" in content
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_username(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.LOOKUP_USERNAME_INPUT_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_first_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.LOOKUP_FIRST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_last_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.LOOKUP_LAST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_disambiguating_device_id(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.LOOKUP_DISAMBIGUATE_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_next_action(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.LOOKUP_NEXT_ACTION_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_identity_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.KB_TICKET_IDENTITY_METHOD_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_username(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.KB_TICKET_USERNAME_INPUT_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_email(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.KB_TICKET_EMAIL_INPUT_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_number(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.TICKET_LOOKUP_NUMBER_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.TICKET_LOOKUP_METHOD_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_user(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return (
                Config.TICKET_LOOKUP_USER_PROMPT.lower() in content
                or Config.TICKET_LOOKUP_USERNAME_PROMPT.lower() in content
            )
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_username(conversation_history: list) -> bool:
        """Return True when the most recent assistant message asked for username in the ticket-by-user flow."""
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.TICKET_LOOKUP_USERNAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_first_name(conversation_history: list) -> bool:
        """Return True when the most recent assistant message asked for first name in the ticket-by-user flow."""
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.TICKET_LOOKUP_USER_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_last_name(conversation_history: list) -> bool:
        """Return True when the most recent assistant message asked for last name in the ticket-by-user flow."""
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return Config.TICKET_LOOKUP_USER_LAST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def get_ticket_lookup_first_name_from_history(conversation_history: list) -> str:
        """Return the user reply that followed the ticket lookup first-name prompt."""
        for i, msg in enumerate(conversation_history):
            if (
                msg.get("role") == "assistant"
                and Config.TICKET_LOOKUP_USER_PROMPT.lower() in (msg.get("content") or "").lower()
                and i + 1 < len(conversation_history)
                and conversation_history[i + 1].get("role") == "user"
            ):
                return conversation_history[i + 1].get("content", "").strip()
        return ""

    # ── Extraction helpers ────────────────────────────────────────────────────

    @staticmethod
    def extract_first_last_name(user_input: str):
        explicit = re.search(
            r"first\s+name\s*(?:is|:)?\s*([A-Za-z'\-]+).*last\s+name\s*(?:is|:)?\s*([A-Za-z'\-]+)",
            user_input,
            flags=re.IGNORECASE,
        )
        if explicit:
            return explicit.group(1), explicit.group(2)
        cleaned = re.sub(r"[^A-Za-z'\-\s]", " ", user_input).strip()
        tokens = [t for t in cleaned.split() if t]
        if len(tokens) >= 2:
            return tokens[0], tokens[-1]
        return None, None

    @staticmethod
    def extract_identity_value(user_input: str):
        email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", user_input)
        if email_match:
            return email_match.group(0), "email"
        username_match = re.search(r"\b[a-zA-Z][a-zA-Z0-9._-]{2,}\b", user_input)
        if username_match:
            return username_match.group(0), "username"
        return None, None

    @staticmethod
    def normalize_lookup_username(identity_value: str, identity_kind: str) -> str:
        if identity_kind == "email":
            return identity_value.split("@", 1)[0].strip().lower()
        return identity_value.strip().lower()

    @staticmethod
    def extract_ticket_id_from_input(user_input: str) -> str:
        match = re.search(r"\b(\d{4,})\b", user_input)
        return match.group(1) if match else ""

    @staticmethod
    def extract_lookup_by_keyword(user_input: str) -> str:
        """If the message contains a 'by <keyword>' direction, return 'username', 'name', or 'number'."""
        msg = user_input.lower()
        if "by" not in msg:
            return ""
        if re.search(r"\bby\s+username\b", msg):
            return "username"
        if re.search(r"\bby\s+(user|name|first\s+name|last\s+name)\b", msg):
            return "name"
        if re.search(r"\bby\s+(number|ticket\s*number|ticket|id|ticket\s*id)\b", msg):
            return "number"
        return ""

    @staticmethod
    def get_first_name_from_lookup_history(conversation_history: list) -> str:
        for i, msg in enumerate(conversation_history):
            if (
                msg.get("role") == "assistant"
                and Config.LOOKUP_FIRST_NAME_PROMPT.lower() in (msg.get("content") or "").lower()
                and i + 1 < len(conversation_history)
                and conversation_history[i + 1].get("role") == "user"
            ):
                return conversation_history[i + 1].get("content", "").strip()
        return ""

    @staticmethod
    def get_username_from_lookup_result(conversation_history: list) -> str:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "user found:" in content.lower() or "match 1:" in content.lower():
                match = re.search(r"-\s*Username:\s*(\S+)", content, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        return ""

    @staticmethod
    def get_user_by_match_number(conversation_history: list, match_num: int) -> str:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "users found with that name:" not in content.lower():
                continue
            pattern = rf"Match {match_num}:\n((?:- [^\n]+\n?)+)"
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                return m.group(0).strip()
        return ""

    @staticmethod
    def user_reports_failed_steps(user_input: str, conversation_history: list) -> bool:
        msg = user_input.lower()
        if not any(s in msg for s in Config.FOLLOWUP_FAILURE_SIGNALS):
            return False
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content", "")
            had_steps = "1." in content and "2." in content
            had_escalation = Config.ESCALATION_SUFFIX in content
            return had_steps and not had_escalation
        return False

    @staticmethod
    def ticket_already_created_in_session(conversation_history: list) -> str:
        """Return the most recent ticket ID if a ticket was created in this conversation, else ''."""
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "ticket created successfully" in content.lower():
                match = re.search(r"ID:\s*(\S+)", content, re.IGNORECASE)
                return match.group(1).rstrip(".,;)") if match else "unknown"
        return ""

    @staticmethod
    def last_assistant_warned_about_duplicate_ticket(conversation_history: list) -> bool:
        """Return True when the last assistant message was a duplicate ticket warning."""
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return "ticket was already opened in this conversation" in (message.get("content") or "").lower()
        return False


# ════════════════════════════════════════════════════
# ORCHESTRATOR
# ════════════════════════════════════════════════════

class Orchestrator:
    """
    MAF orchestrator — routes every user message through:
      TriageAgent    → classifies intent, urgency, and routing decision
      KnowledgeAgent → searches the knowledge base and returns step-by-step answers
      ActionAgent    → executes operational tasks (lookups, device checks, tickets)
    """

    def __init__(
        self,
        triage_agent,
        knowledge_agent,
        action_agent,
        retrieval: RetrievalEngine,
        detector: ConversationDetector,
    ):
        self.triage_agent = triage_agent
        self.knowledge_agent = knowledge_agent
        self.action_agent = action_agent
        self.retrieval = retrieval
        self.detector = detector

    async def run(self, user_input: str, conversation_history: list) -> str:
        print("\n[Orchestrator] Starting triage...")

        history_context = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in conversation_history[-Config.HISTORY_LIMIT:]
        )
        triage_prompt = (
            f"Conversation so far:\n{history_context}\n\nLatest message: {user_input}"
            if history_context
            else user_input
        )

        # ── Step 1: Triage ────────────────────────────────────────────────────
        if self.triage_agent is None:
            print("[Orchestrator] Triage agent unavailable — defaulting to knowledge route")
            triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}
        else:
            try:
                triage_response = await self.triage_agent.run(triage_prompt)
                triage_raw = triage_response.text.strip()
                print(f"[Orchestrator] Triage: {triage_raw}")
                triage_data = json.loads(triage_raw)
            except Exception as e:
                print(f"[Orchestrator] Triage failed: {e} — defaulting to knowledge route")
                triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}

        route_to = triage_data.get("route_to", "knowledge")
        urgency = triage_data.get("urgency", "medium")
        category = triage_data.get("category", "General")

        # Force action route on explicit ticket request
        if self.detector.looks_like_ticket_request(user_input):
            print("[Orchestrator] Overriding route to ACTION due to explicit ticket request.")
            route_to = "action"

        explicit_action_intent = (
            self.detector.looks_like_tool_request(user_input)
            or self.detector.looks_like_ticket_request(user_input)
        )
        if route_to == "action" and not explicit_action_intent:
            print("[Orchestrator] Action route kept from TRIAGE (weak explicit signal, context-based action intent)")

        print(f"[Orchestrator] Route → {route_to.upper()} | Urgency: {urgency} | Category: {category}")

        # ── Step 2: Clarification ─────────────────────────────────────────────
        if route_to == "clarify":
            return triage_data.get(
                "clarifying_question",
                "Could you provide more details about the issue?",
            )

        # ── Step 3a: Knowledge Agent ──────────────────────────────────────────
        if route_to == "knowledge":
            print("[Orchestrator] Dispatching → KnowledgeAgent")
            if self.knowledge_agent is None:
                return (
                    "Knowledge agent is unavailable because backend AI components failed to initialize. "
                    "Please check app settings and startup logs."
                )

            enriched_query = self.retrieval.build_retrieval_query(user_input, conversation_history)
            docs = self.retrieval.get_search_results(enriched_query, top_k=Config.KNOWLEDGE_TOP_K)

            # Error-code-aware fallback
            error_code = self.retrieval.extract_error_code(user_input)
            if error_code and docs and not self.retrieval.docs_contain_error_code(docs, error_code):
                fallback_query = f"error code {error_code} {user_input}"
                print(f"[Orchestrator] Retrying retrieval with error-code fallback query: '{fallback_query}'")
                fallback_docs = self.retrieval.get_search_results(fallback_query, top_k=Config.KNOWLEDGE_TOP_K)
                if fallback_docs:
                    docs = fallback_docs

            if error_code and not self.retrieval.docs_contain_error_code(docs, error_code):
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
                knowledge_response = await self.knowledge_agent.run(knowledge_prompt)
                return knowledge_response.text.strip()
            except Exception as e:
                return f"Knowledge base lookup failed: {e}"

        # ── Step 3b: Action Agent ─────────────────────────────────────────────
        if route_to == "action":
            print("[Orchestrator] Dispatching → ActionAgent")
            if self.action_agent is None:
                return "Action agent is unavailable because Azure OpenAI settings are missing or invalid."
            try:
                action_prompt = (
                    f"Conversation history:\n{history_context}\n\nUser message: {user_input}"
                    if history_context
                    else user_input
                )
                action_response = await self.action_agent.run(action_prompt)
                return action_response.text.strip()
            except Exception as e:
                return f"Action execution failed: {e}"

        return "I was unable to process your request. Please try again."


# ════════════════════════════════════════════════════
# AGENT CONTROLLER
# ════════════════════════════════════════════════════

class AgentController:
    """
    Top-level conversation controller.

    Evaluates every incoming user message, runs all pre-checks for active
    multi-turn flows (KB ticket, lookup, ticket lookup), and delegates to
    the Orchestrator for all other routing.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        action_agent,
        detector: ConversationDetector,
        escalation: EscalationService,
        openai_client,
    ):
        self.orchestrator = orchestrator
        self.action_agent = action_agent
        self.detector = detector
        self.escalation = escalation
        self.openai_client = openai_client

    # ── Ticket helpers ────────────────────────────────────────────────────────

    @staticmethod
    def build_ticket_prompt(ctx: dict) -> str:
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

    def extract_ticket_context(self, conversation_history: list) -> dict:
        """Use the LLM to extract structured ticket fields from conversation history."""
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in conversation_history[-Config.HISTORY_LIMIT:]
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
            response = self.openai_client.chat.completions.create(
                model=Config.OPENAI_DEPLOYMENT,
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

    # ── Main controller ───────────────────────────────────────────────────────

    async def handle_user_message(self, user_input: str, conversation_history: list):
        print("\n[Agent Controller] Evaluating message...")
        d = self.detector

        # Pre-check: repeated input — send clarification prompt
        if conversation_history:
            last_user_msg = next(
                (m.get("content", "") for m in reversed(conversation_history) if m.get("role") == "user"),
                None,
            )
            if last_user_msg and last_user_msg.strip().lower() == user_input.strip().lower():
                print("[Agent Controller] Repeated input detected — sending clarification prompt.")
                return (
                    "It looks like you sent the same message again. "
                    "Are you still waiting for something, or would you like to rephrase your request?"
                ), True

        # Pre-check: KB ticket flow — email value received
        if conversation_history and d.last_assistant_asked_for_kb_ticket_email(conversation_history):
            email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", user_input)
            if not email_match:
                return "That doesn't look like a valid email address. Please try again.", True
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            ctx = self.extract_ticket_context(conversation_history)
            ctx["user"] = email_match.group(0)
            tool_prompt = self.build_ticket_prompt(ctx)
            print(f"[DEBUG] KB escalation ticket prompt (email): {tool_prompt}")
            action_response = await self.action_agent.run(tool_prompt)
            return action_response.text, True

        # Pre-check: KB ticket flow — username value received
        if conversation_history and d.last_assistant_asked_for_kb_ticket_username(conversation_history):
            username = user_input.strip()
            if not username:
                return Config.KB_TICKET_USERNAME_INPUT_PROMPT, True
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            ctx = self.extract_ticket_context(conversation_history)
            ctx["user"] = d.normalize_lookup_username(username, "username")
            tool_prompt = self.build_ticket_prompt(ctx)
            print(f"[DEBUG] KB escalation ticket prompt (username): {tool_prompt}")
            action_response = await self.action_agent.run(tool_prompt)
            return action_response.text, True

        # Pre-check: KB ticket flow — method choice (username vs email)
        if conversation_history and d.last_assistant_asked_for_kb_ticket_identity_method(conversation_history):
            choice = user_input.strip().lower()
            if "username" in choice:
                return Config.KB_TICKET_USERNAME_INPUT_PROMPT, True
            elif "email" in choice:
                return Config.KB_TICKET_EMAIL_INPUT_PROMPT, True
            else:
                return Config.KB_TICKET_IDENTITY_METHOD_PROMPT, True

        # Pre-check: ticket confirmation following a prior escalation offer
        is_confirmation = (
            d.looks_like_ticket_confirmation(user_input)
            and d.last_assistant_offered_escalation(conversation_history)
        )
        if is_confirmation:
            print("[Agent Controller] Decision → TICKET CONFIRMATION → ActionAgent")
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            ctx = self.extract_ticket_context(conversation_history)
            if ctx["user"] == "unknown":
                print("[Agent Controller] User identity unknown — requesting identity method before ticket creation")
                return Config.KB_TICKET_IDENTITY_METHOD_PROMPT, True
            tool_prompt = self.build_ticket_prompt(ctx)
            print(f"[DEBUG] Ticket prompt sent to agent: {tool_prompt}")
            action_response = await self.action_agent.run(tool_prompt)
            return action_response.text, True

        # Identity for lookup received
        if conversation_history and d.last_assistant_requested_identity_for_lookup(conversation_history):
            identity_value, identity_kind = d.extract_identity_value(user_input)
            if not identity_value:
                return (
                    "I still need either your username or your email to continue account lookup. "
                    "Please provide one of those."
                ), True
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            lookup_username = d.normalize_lookup_username(identity_value, identity_kind)
            followup_prompt = (
                "The user provided account identity details.\n"
                f"Provided {identity_kind}: {identity_value}\n"
                f"Username for lookup_user: {lookup_username}\n\n"
                "Use lookup_user with that username now. "
                "Then continue the ticket workflow using conversation context and create the ticket when ready."
            )
            action_response = await self.action_agent.run(followup_prompt)
            return action_response.text, True

        # Name fields detected — continue action flow
        if conversation_history and d.last_assistant_requested_name_fields(conversation_history):
            first_name, last_name = d.extract_first_last_name(user_input)
            if first_name and last_name:
                print("[Agent Controller] Name fields detected in user reply — continuing action flow.")
                return Config.IDENTITY_LOOKUP_PROMPT, True

        # Ticket field request reply — auto-create ticket from comma-separated reply
        if conversation_history:
            last_msg = conversation_history[-1]
            if last_msg.get("role") == "assistant" and "required fields to create the ticket" in last_msg.get("content", ""):
                parts = [p.strip() for p in user_input.split(",")]
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
                if not self.action_agent:
                    return "Action agent is unavailable because Azure OpenAI settings are missing.", True
                action_response = await self.action_agent.run(ticket_prompt)
                return action_response.text, True

        # ── Lookup flows ──────────────────────────────────────────────────────

        # Step 4c: Match number — disambiguate multiple name matches
        if conversation_history and d.last_assistant_asked_for_disambiguating_device_id(conversation_history):
            num_match = re.search(r"\b(\d+)\b", user_input)
            if not num_match:
                return Config.LOOKUP_DISAMBIGUATE_PROMPT, True
            match_num = int(num_match.group(1))
            user_block = d.get_user_by_match_number(conversation_history, match_num)
            if not user_block:
                return Config.LOOKUP_DISAMBIGUATE_PROMPT, True
            print(f"[Agent Controller] Decision → DISAMBIGUATE by match number: {match_num}")
            return f"User found:\n{user_block}\n\n{Config.LOOKUP_NEXT_ACTION_PROMPT}", True

        # Step 4d: Next action chosen after a single successful lookup
        if conversation_history and d.last_assistant_asked_for_lookup_next_action(conversation_history):
            choice = user_input.strip().lower()
            username = d.get_username_from_lookup_result(conversation_history)
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            if "device" in choice:
                print(f"[Agent Controller] Decision → CHECK DEVICE for username: {username}")
                device_prompt = f"Use check_device_status with '{username}'. Display the full device details."
                action_response = await self.action_agent.run(device_prompt)
                return action_response.text, True
            elif "ticket" in choice:
                print(f"[Agent Controller] Decision → CREATE TICKET for username: {username}")
                history_context = "\n".join(
                    f"{m['role'].upper()}: {m['content']}"
                    for m in conversation_history[-Config.HISTORY_LIMIT:]
                )
                ticket_prompt = (
                    f"Conversation history:\n{history_context}\n\n"
                    f"The user wants to create a support ticket for username '{username}'. "
                    "Collect any missing ticket details from the conversation history and create the ticket."
                )
                action_response = await self.action_agent.run(ticket_prompt)
                return action_response.text, True
            else:
                return Config.LOOKUP_NEXT_ACTION_PROMPT, True

        # Step 4b: Last name received — perform name-based lookup
        if conversation_history and d.last_assistant_asked_for_lookup_last_name(conversation_history):
            last_name = user_input.strip()
            first_name = d.get_first_name_from_lookup_history(conversation_history)
            if not first_name:
                return "I couldn't retrieve the first name. Please start the lookup again.", True
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP by name: {first_name} {last_name}")
            lookup_prompt = (
                f"Use lookup_user with first_name='{first_name}' and last_name='{last_name}'. "
                "Display all the user details returned."
            )
            action_response = await self.action_agent.run(lookup_prompt)
            response_text = action_response.text
            if "user found:" in response_text.lower():
                response_text = response_text.rstrip() + f"\n\n{Config.LOOKUP_NEXT_ACTION_PROMPT}"
            return response_text, True

        # Step 3b: First name received — ask for last name
        if conversation_history and d.last_assistant_asked_for_lookup_first_name(conversation_history):
            print("[Agent Controller] First name received — asking for last name")
            return Config.LOOKUP_LAST_NAME_PROMPT, True

        # Step 3a: Username received — perform username-based lookup
        if conversation_history and d.last_assistant_asked_for_lookup_username(conversation_history):
            username = user_input.strip()
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP by username: {username}")
            lookup_prompt = (
                f"Use lookup_user with username='{username}'. "
                "Display all the user details returned."
            )
            action_response = await self.action_agent.run(lookup_prompt)
            response_text = action_response.text
            if "user found:" in response_text.lower():
                response_text = response_text.rstrip() + f"\n\n{Config.LOOKUP_NEXT_ACTION_PROMPT}"
            return response_text, True

        # Step 2: Lookup method chosen — ask for the appropriate identifier
        if conversation_history and d.last_assistant_asked_lookup_method(conversation_history):
            choice = user_input.strip().lower()
            if "username" in choice or choice == "1":
                return Config.LOOKUP_USERNAME_INPUT_PROMPT, True
            elif "name" in choice or choice == "2":
                return Config.LOOKUP_FIRST_NAME_PROMPT, True
            else:
                return Config.LOOKUP_METHOD_PROMPT, True

        # ── Ticket lookup flows ───────────────────────────────────────────────

        # Ticket number received — perform ticket lookup
        if conversation_history and d.last_assistant_asked_for_ticket_number(conversation_history):
            ticket_id = d.extract_ticket_id_from_input(user_input) or user_input.strip()
            if not ticket_id:
                return Config.TICKET_LOOKUP_NUMBER_PROMPT, True
            if not self.action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKET: {ticket_id}")
            ticket_prompt = f"Use lookup_ticket with ticket_id='{ticket_id}'. Display all the ticket details returned."
            action_response = await self.action_agent.run(ticket_prompt)
            return action_response.text, True

        # Ticket-by-user last name received — complete the name-based ticket lookup
        if conversation_history and d.last_assistant_asked_for_ticket_lookup_last_name(conversation_history):
            last_name = user_input.strip()
            first_name = d.get_ticket_lookup_first_name_from_history(conversation_history)
            if first_name and last_name:
                if not self.action_agent:
                    return "Action agent is unavailable because Azure OpenAI settings are missing.", True
                print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (name): {first_name} {last_name}")
                ticket_prompt = f"Use lookup_tickets_by_user with first_name='{first_name}' and last_name='{last_name}'. Display all the tickets returned."
                action_response = await self.action_agent.run(ticket_prompt)
                return action_response.text, True
            return Config.TICKET_LOOKUP_USER_LAST_NAME_PROMPT, True

        # Ticket-by-user first name received — ask for last name
        if conversation_history and d.last_assistant_asked_for_ticket_lookup_first_name(conversation_history):
            print("[Agent Controller] Decision → TICKET LOOKUP BY NAME → first name received, prompting for last name")
            return Config.TICKET_LOOKUP_USER_LAST_NAME_PROMPT, True

        # Ticket-by-username received — look up tickets by username
        if conversation_history and d.last_assistant_asked_for_ticket_lookup_username(conversation_history):
            identity_value, identity_kind = d.extract_identity_value(user_input)
            if identity_value:
                lookup_username = d.normalize_lookup_username(identity_value, identity_kind)
                if not self.action_agent:
                    return "Action agent is unavailable because Azure OpenAI settings are missing.", True
                print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (username): {lookup_username}")
                ticket_prompt = f"Use lookup_tickets_by_user with username='{lookup_username}'. Display all the tickets returned."
                action_response = await self.action_agent.run(ticket_prompt)
                return action_response.text, True
            return Config.TICKET_LOOKUP_USERNAME_PROMPT, True  # re-ask if identity couldn't be parsed

        # Ticket lookup method choice received — route to number or user sub-flow
        if conversation_history and d.last_assistant_asked_for_ticket_lookup_method(conversation_history):
            choice = user_input.strip().lower()
            if "number" in choice or choice == "1":
                return Config.TICKET_LOOKUP_NUMBER_PROMPT, True
            elif choice == "username" or "username" in choice:
                return Config.TICKET_LOOKUP_USERNAME_PROMPT, True
            elif "name" in choice or "user" in choice or choice == "2":
                return Config.TICKET_LOOKUP_USER_PROMPT, True
            else:
                return Config.TICKET_LOOKUP_METHOD_PROMPT, True

        # Ticket lookup request — extract inline ticket ID or prompt for method
        if d.looks_like_ticket_lookup_request(user_input):
            ticket_id = d.extract_ticket_id_from_input(user_input)
            if ticket_id:
                if not self.action_agent:
                    return "Action agent is unavailable because Azure OpenAI settings are missing.", True
                print(f"[Agent Controller] Decision → LOOKUP TICKET (inline): {ticket_id}")
                ticket_prompt = f"Use lookup_ticket with ticket_id='{ticket_id}'. Display all the ticket details returned."
                action_response = await self.action_agent.run(ticket_prompt)
                return action_response.text, True
            by_method = d.extract_lookup_by_keyword(user_input)
            if by_method == "username":
                print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for username")
                return Config.TICKET_LOOKUP_USERNAME_PROMPT, True
            if by_method == "name":
                print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for first/last name")
                return Config.TICKET_LOOKUP_USER_PROMPT, True
            if by_method == "number":
                print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for ticket number")
                return Config.TICKET_LOOKUP_NUMBER_PROMPT, True
            return Config.TICKET_LOOKUP_METHOD_PROMPT, True

        # Direct user lookup request — start method selection
        if d.looks_like_direct_lookup_request(user_input):
            print("[Agent Controller] Decision → DIRECT LOOKUP → prompting for method")
            return Config.LOOKUP_METHOD_PROMPT, True

        # Failed troubleshooting steps — proactively offer escalation
        if d.user_reports_failed_steps(user_input, conversation_history):
            print("[Agent Controller] Decision → FOLLOW-UP FAILURE → OFFER ESCALATION")
            return (
                "Thanks for trying those steps."
                + Config.ESCALATION_SUFFIX
                + "\n\nWould you like me to create a support ticket for this issue?"
            ), True

        # Duplicate ticket guard — prevent auto-creating a second ticket for the same session
        if d.last_assistant_warned_about_duplicate_ticket(conversation_history):
            if d.looks_like_ticket_confirmation(user_input):
                print("[Agent Controller] Decision → DUPLICATE TICKET CONFIRMED → prompting for new issue")
                return (
                    "Please describe the new issue you'd like to open a ticket for."
                ), True
            if user_input.strip().lower() in ("no", "no thanks", "cancel", "never mind", "nevermind", "nope"):
                return "Understood. No additional ticket will be created.", True

        if d.looks_like_ticket_request(user_input):
            existing_ticket_id = d.ticket_already_created_in_session(conversation_history)
            if existing_ticket_id:
                print(f"[Agent Controller] Decision → DUPLICATE TICKET GUARD (existing: {existing_ticket_id})")
                return (
                    f"A ticket was already opened in this conversation (Ticket ID: {existing_ticket_id}). "
                    "Would you like to open an additional ticket for a different issue? "
                    "Reply 'yes' to proceed or 'no' to cancel."
                ), True

        # Delegate all other routing to the MAF Orchestrator
        response = await self.orchestrator.run(user_input, conversation_history)
        if self.escalation.should_run_escalation_check(response):
            final_response = self.escalation.check_escalation(response)
        else:
            final_response = response

        if Config.ESCALATION_SUFFIX in final_response:
            final_response += "\n\nWould you like me to create a support ticket for this issue?"

        return final_response, True


# ════════════════════════════════════════════════════
# MAIN — wires all classes and runs the chat loop
# ════════════════════════════════════════════════════

async def main():
    print("═" * 76)
    print("  Azure RAG IT Support Agent + Microsoft Agent Framework")
    print("  Memory ✓  Clarification ✓  Multi-Turn ✓  Escalation ✓  Orchestrator ✓")
    print("  Agents: TriageAgent · KnowledgeAgent · ActionAgent")
    print("═" * 76)
    print("Commands: 'exit' to quit · 'reset' to clear history\n")
    print("\nHello I am an IT helpdesk support assistant. \n\nHow can I help you today?\n")

    # Build Azure clients
    raw_openai = None
    if Config.OPENAI_ENDPOINT and Config.OPENAI_KEY and Config.OPENAI_DEPLOYMENT:
        raw_openai = AzureOpenAI(
            api_key=Config.OPENAI_KEY,
            api_version=Config.OPENAI_API_VERSION,
            azure_endpoint=Config.OPENAI_ENDPOINT,
        )

    az_search = None
    if Config.SEARCH_ENDPOINT and Config.SEARCH_KEY and Config.SEARCH_INDEX:
        az_search = SearchClient(
            endpoint=Config.SEARCH_ENDPOINT,
            index_name=Config.SEARCH_INDEX,
            credential=AzureKeyCredential(Config.SEARCH_KEY),
        )

    # Assemble services
    agents = AgentFactory()
    retrieval = RetrievalEngine(raw_openai, az_search)
    escalation = EscalationService(raw_openai)
    detector = ConversationDetector()

    orchestrator = Orchestrator(
        triage_agent=agents.triage_agent,
        knowledge_agent=agents.knowledge_agent,
        action_agent=agents.action_agent,
        retrieval=retrieval,
        detector=detector,
    )

    controller = AgentController(
        orchestrator=orchestrator,
        action_agent=agents.action_agent,
        detector=detector,
        escalation=escalation,
        openai_client=raw_openai,
    )

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

        response, should_store = await controller.handle_user_message(user_input, conversation_history)

        print(f"\nAssistant: {response}")

        if should_store:
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
