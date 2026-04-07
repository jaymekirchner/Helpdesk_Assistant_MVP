"""MAF tool functions that wrap MCP server calls for the Action Agent."""

import logging
from typing import Annotated
from pydantic import Field

from config.settings import tool
from config.constants import LOOKUP_DISAMBIGUATE_PROMPT, LOOKUP_NEXT_ACTION_PROMPT
from services.mcp_client import mcp_client

logger = logging.getLogger(__name__)


def _format_single_user(record: dict, fallback_username: str = "") -> str:
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
    logger.info("lookup_user called with args: %s", args)
    try:
        result = mcp_client.call_tool("lookup_user", args)
        records = mcp_client.extract_records(result)
        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return envelope.get("error") or "User lookup failed."
        data = envelope.get("data")
        if isinstance(data, list):
            count = envelope.get("count", len(data))
            if count == 1:
                return "User found:\n" + _format_single_user(data[0])
            lines = [f"{count} users found with that name:"]
            for i, record in enumerate(data, 1):
                lines.append(f"\nMatch {i}:\n" + _format_single_user(record))
            lines.append(f"\n{LOOKUP_DISAMBIGUATE_PROMPT}")
            return "\n".join(lines)
        result_text = "User found:\n" + _format_single_user(data or {}, username)
        logger.info("lookup_user result: %s", result_text[:300])
        return result_text
    except Exception as e:
        logger.error("lookup_user failed: %s", e)
        return f"Error looking up user via MCP: {str(e)}"


@tool(
    name="check_device_status",
    description="Check the status of a company device by device ID, username, or first and last name. Use for laptop or device status requests.",
)
def check_device_status(
    device_or_username: Annotated[str, Field(description="Device ID (for example LAPTOP-1001) or username (for example john.doe). Leave empty if searching by name.")] = "",
    first_name: Annotated[str, Field(description="Employee first name. Use together with last_name when device ID and username are unknown.")] = "",
    last_name: Annotated[str, Field(description="Employee last name. Use together with first_name when device ID and username are unknown.")] = "",
) -> str:
    try:
        args: dict = {}
        if device_or_username:
            args["device_or_username"] = device_or_username
        if first_name:
            args["first_name"] = first_name
        if last_name:
            args["last_name"] = last_name
        logger.info("check_device_status called with args: %s", args)
        result = mcp_client.call_tool("check_device_status", args)
        records = mcp_client.extract_records(result)
        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return envelope.get("error") or "Device lookup failed."
        record = envelope.get("data") or {}
        result_text = (
            "Device status:\n\n"
            "Match 1:\n"
            f"- Device ID: {record.get('device_id', 'Unknown')}\n"
            f"- Username: {record.get('username', 'unknown')}\n"
            f"- Status: {record.get('status', 'Unknown')}\n"
            f"- VPN Client: {record.get('vpn_client', 'Unknown')}\n"
            f"- Last Seen: {record.get('last_seen', 'Unknown')}"
        )
        logger.info("check_device_status result: %s", result_text[:300])
        return result_text
    except Exception as e:
        logger.error("check_device_status failed: %s", e)
        return f"Error checking device status via MCP: {str(e)}"


@tool(
    name="lookup_ticket",
    description="Look up an existing support ticket by ticket ID. Returns status, category, subject, and the associated user's name and email.",
)
def lookup_ticket(
    ticket_id: Annotated[str, Field(description="The ticket ID or ticket number to look up")],
) -> str:
    logger.info("lookup_ticket called with ticket_id: %s", ticket_id)
    try:
        result = mcp_client.call_tool("lookup_ticket", {"ticket_id": ticket_id})
        records = mcp_client.extract_records(result)
        envelope = records[0] if records else {}
        if not isinstance(envelope, dict):
            return str(envelope)
        if not envelope.get("success"):
            return envelope.get("error") or "Ticket lookup failed."
        data = envelope.get("data") or {}
        full_name = " ".join(filter(None, [data.get("first_name"), data.get("last_name")])).strip() or "Unknown"
        result_text = (
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
        logger.debug("lookup_ticket result: %s", result_text[:300])
        return result_text
    except Exception as e:
        logger.error("lookup_ticket failed: %s", e)
        return f"Error looking up ticket via MCP: {str(e)}"


@tool(
    name="lookup_tickets_by_user",
    description="Look up all support tickets for a specific user by username or first and last name.",
)
def lookup_tickets_by_user(
    username: Annotated[str, Field(description="Employee username, e.g. john.doe. Use when username is known.")] = "",
    first_name: Annotated[str, Field(description="Employee first name. Use with last_name when username is unknown.")] = "",
    last_name: Annotated[str, Field(description="Employee last name. Use with first_name when username is unknown.")] = "",
) -> str:
    logger.info("lookup_tickets_by_user called with username=%s, first_name=%s, last_name=%s", username, first_name, last_name)
    try:
        result = mcp_client.call_tool(
            "lookup_tickets_by_user",
            {"username": username, "first_name": first_name, "last_name": last_name},
        )
        records = mcp_client.extract_records(result)
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
        logger.error("lookup_tickets_by_user failed: %s", e)
        return f"Error looking up tickets by user via MCP: {str(e)}"


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
    source_language: Annotated[str, Field(description="The language the user wrote in, e.g. 'Spanish', 'French'. Omit or pass 'English' if the user wrote in English.")] = "English",
    first_name: Annotated[str, Field(description="Requester's first name for user lookup")] = "",
    last_name: Annotated[str, Field(description="Requester's last name for user lookup")] = "",
    additional_cc_emails: Annotated[list[str], Field(description="Extra email addresses to CC on the ticket")] = [],
) -> str:
    """Create a ticket via MCP server tool."""
    logger.info("create_ticket called for user=%s, category=%s, severity=%s", user, category, severity)
    try:
        result = mcp_client.call_tool(
            "create_ticket",
            {
                "issue": issue,
                "user": user,
                "category": category,
                "severity": severity,
                "impacted_system": impacted_system,
                "source_language": source_language.strip() if source_language else "",
                "first_name": first_name,
                "last_name": last_name,
                "additional_cc_emails": additional_cc_emails or [],
            },
        )
        records = mcp_client.extract_records(result)

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
        logger.info("create_ticket succeeded: %s", result_text)
        return result_text
    except Exception as e:
        logger.error("create_ticket failed: %s", e)
        return f"Error calling MCP ticket tool: {e}"


# Convenience list for agent initialization
ALL_TOOLS = [lookup_user, check_device_status, create_ticket, lookup_ticket, lookup_tickets_by_user]
