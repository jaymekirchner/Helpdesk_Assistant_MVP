import os
import re
import base64
import datetime
import logging

import psycopg2
import requests
from openai import AzureOpenAI
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

logger = logging.getLogger(__name__)

mcp = FastMCP("IT Helpdesk MCP Server")

# ---------------------------------------------------------------------------
# Azure OpenAI client (for translation)
# ---------------------------------------------------------------------------
_oai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_oai_key = os.getenv("AZURE_OPENAI_API_KEY", "")
_oai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
_oai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

_openai_client: AzureOpenAI | None = None
if _oai_endpoint and _oai_key and _oai_deployment:
    _openai_client = AzureOpenAI(
        api_key=_oai_key,
        api_version=_oai_api_version,
        azure_endpoint=_oai_endpoint,
    )


def _translate_to_english(text: str, source_language: str) -> str:
    """Translate *text* from *source_language* to English using Azure OpenAI.
    Returns the original text unchanged if the client is unavailable or the call fails."""
    if not _openai_client or not _oai_deployment:
        logger.warning("Azure OpenAI client not configured — skipping translation.")
        return text
    try:
        response = _openai_client.chat.completions.create(
            model=_oai_deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional translator. Translate the following text "
                        f"from {source_language} to English. Return ONLY the translated text, "
                        "with no commentary, preamble, or formatting."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2, #randonmness; lower value makes output more deterministic and consistent
            max_tokens=1024, #approx 750 words
        )
        translated = (response.choices[0].message.content or "").strip()
        return translated if translated else text
    except Exception as e:
        logger.error("Failed to translate text: %s", e)
        return text

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

# Patterns that indicate prompt-injection or wildcard/bulk-data attempts.
_INJECTION_PATTERNS = re.compile(
    r"ignore\s+(previous|prior|above|all)\s+instructions?"
    r"|print\s+(your\s+)?(prompt|system\s+prompt|instructions?)"
    r"|act\s+as\s+(a\s+)?(different|new|another|general)"
    r"|you\s+are\s+now"
    r"|reveal\s+(your\s+)?(prompt|instructions?|config)"
    r"|run\s+(a\s+)?query"
    r"|execute\s+(sql|command|script)"
    r"|\ball\s+users\b|\ball\s+devices\b|\ball\s+tickets\b"
    r"|\bselect\s+\*\b|\bdrop\s+table\b|\bdelete\s+from\b",
    re.IGNORECASE,
)

_MAX_FIELD_LEN = 200  # reasonable upper bound for any single lookup field


def _guard(value: str, field_name: str) -> str | None:
    """Return an error message string if the value looks malicious or invalid,
    otherwise return None (safe to proceed)."""
    if not isinstance(value, str):
        return f"Invalid type for '{field_name}'."
    if len(value) > _MAX_FIELD_LEN:
        return f"'{field_name}' value exceeds the maximum allowed length."
    if _INJECTION_PATTERNS.search(value):
        return f"Suspicious or disallowed content detected in '{field_name}'."
    return None


# @mcp.tool
# def health_check() -> dict:
#     """Return server readiness status and connectivity checks for all dependencies."""
#     checks = {}

#     # Postgres
#     conn_str = _postgres_conn_string()
#     if conn_str:
#         try:
#             with psycopg2.connect(conn_str) as conn:
#                 with conn.cursor() as cur:
#                     cur.execute("SELECT 1")
#             checks["postgres"] = "ok"
#         except psycopg2.Error as e:
#             checks["postgres"] = f"error: {e}"
#     else:
#         checks["postgres"] = "not configured"

#     # Freshworks
#     if os.getenv("FRESHWORKS_API_KEY") and os.getenv("FRESHWORKS_DOMAIN"):
#         checks["freshworks"] = "configured"
#     else:
#         checks["freshworks"] = "not configured"

#     # Azure OpenAI (translation)
#     if _openai_client and _oai_deployment:
#         checks["azure_openai"] = "configured"
#     else:
#         checks["azure_openai"] = "not configured"

#     all_ok = all(v in ("ok", "configured") for v in checks.values())
#     return {
#         "success": all_ok,
#         "error": None if all_ok else "One or more dependencies are unavailable",
#         "data": {
#             "status": "ready" if all_ok else "degraded",
#             "checks": checks,
#             "timestamp_utc": datetime.datetime.utcnow().isoformat(),
#         },
#     }


def _postgres_conn_string() -> str:
    """Retrieve Postgres connection string from environment, or construct from components."""
    conn_str = os.getenv("AZURE_POSTGRESQL_CONNECTION_STRING", "")
    if not conn_str:
        # Backward-compatible fallback for previously used key name.
        conn_str = os.getenv("AZURE_POSTGRESQL_CONNECTIONSTRING", "")
    if conn_str:
        return conn_str
    
    # Fallback: construct from individual components (for backward compatibility)
    user = os.getenv("AZURE_POSTGRESQL_USER", "ithelpdesk_pod2_admin")
    password = os.getenv("AZURE_POSTGRESQL_PASSWORD", "")
    host = os.getenv("AZURE_POSTGRESQL_HOST", "ithelpdesk-pod2-postgres-db.postgres.database.azure.com")
    port = os.getenv("AZURE_POSTGRESQL_PORT", "5432")
    dbname = os.getenv("AZURE_POSTGRESQL_DBNAME", "postgres")
    
    if password:
        return f"dbname={dbname} user={user} password={password} port={port} host={host}"
    return ""


def _freshworks_endpoint() -> str:
    domain = (os.getenv("FRESHWORKS_DOMAIN", "") or "").strip()
    if not domain:
        return ""
    # Accept either subdomain form ("ibm-helpdesk") or full URL/host form.
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/") + "/api/v2/tickets"
    if "." in domain:
        return f"https://{domain.rstrip('/')}/api/v2/tickets"
    return f"https://{domain}.freshservice.com/api/v2/tickets"


def _map_severity_to_priority(severity: str) -> int:
    mapping = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    return mapping.get(severity, 2)


def _map_severity_to_scale3(severity: str) -> int:
    mapping = {"Low": 1, "Medium": 2, "High": 3, "Critical": 3}
    return mapping.get(severity, 2)


def _map_category_to_group_id(category: str) -> int:
    mapping = {
        "VPN": 40000430768,
        "Email": 40000430767,
        "MFA": 40000430756,
        "Device": 40000430763,
        "Account": 40000430756,
        "Software": 40000430767,
        "Hardware": 40000430763,
        "General": 40000430769,
    }
    return mapping.get(category, 40000430769)


def _map_category_to_ticket_type(category: str) -> str:
    mapping = {
        "VPN": "Incident",
        "Email": "Incident",
        "MFA": "Incident",
        "Device": "Incident",
        "Account": "Incident",
        "Software": "Incident",
        "Hardware": "Incident",
        "General": "Service Request",
    }
    return mapping.get(category, "Service Request")


def _resolve_requester_email(
    user: str = "",
    first_name: str = "",
    last_name: str = "",
    additional_cc_emails: list[str] | None = None,
) -> tuple[str, list[str], str]:
    """Return (requester_email, cc_emails, device_id).

    Looks up the user in demo.users by username, email, or first+last name to
    find their email and device_id.  FRESHWORKS_DEFAULT_REQUESTER_EMAIL is
    always added to the CC list.  Any *additional_cc_emails* are appended.
    Falls back to the default email as the requester when no match is found.
    """
    default_email = os.getenv("FRESHWORKS_DEFAULT_REQUESTER_EMAIL", "helpdesk@corp.com")
    requester_email = ""
    device_id = ""

    conn_str = _postgres_conn_string()
    if conn_str:
        try:
            with psycopg2.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    row = None
                    # Try username first
                    if user and user != "unknown" and "@" not in user:
                        cur.execute(
                            "SELECT email, device_id FROM demo.users WHERE LOWER(username) = %s",
                            (user.lower(),),
                        )
                        row = cur.fetchone()
                    # Try email
                    if not row and user and "@" in user:
                        cur.execute(
                            "SELECT email, device_id FROM demo.users WHERE LOWER(email) = %s",
                            (user.lower(),),
                        )
                        row = cur.fetchone()
                    # Try first + last name
                    if not row and first_name and last_name:
                        cur.execute(
                            "SELECT email, device_id FROM demo.users "
                            "WHERE LOWER(first_name) = %s AND LOWER(last_name) = %s",
                            (first_name.lower(), last_name.lower()),
                        )
                        row = cur.fetchone()
                    if row:
                        requester_email = row[0] or ""
                        device_id = row[1] or ""
        except psycopg2.Error as e:
            logger.error("DB lookup failed in _resolve_requester_email: %s", e)

    if not requester_email:
        requester_email = default_email

    # Build CC list — always include the default helpdesk email
    cc_emails: list[str] = []
    if default_email and default_email.lower() != requester_email.lower():
        cc_emails.append(default_email)

    for addr in (additional_cc_emails or []):
        if addr and addr.lower() not in {e.lower() for e in cc_emails} and addr.lower() != requester_email.lower():
            cc_emails.append(addr)

    return requester_email, cc_emails, device_id


def _map_freshworks_status(status_code) -> str:
    """Map Freshworks integer status code to a human-readable string."""
    mapping = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
    try:
        return mapping.get(int(status_code), str(status_code))
    except (TypeError, ValueError):
        return str(status_code) if status_code else "Open"


def _save_ticket_to_postgres(
    ticket_id: str,
    severity: str,
    status: str,
    assignment_group: str,
    username: str,
    first_name: str = "",
    last_name: str = "",
    category: str = "",
    created_at: str = "",
    subject: str = "",
    description_text: str = "",
    ticket_type: str = "",
    source_language: str = "",
) -> None:
    """Persist ticket details to demo.tickets. Resolves user_id and device_id from demo.users.
    Tries username first; falls back to first_name + last_name if username is missing or not found.
    Non-fatal: logs errors but never raises so ticket creation always succeeds."""
    conn_str = _postgres_conn_string()
    if not conn_str:
        logger.warning("Postgres connection string not configured — skipping ticket save.")
        return
    try:
        with psycopg2.connect(conn_str) as conn:
            with conn.cursor() as cur:
                # Resolve user_id and device_id — try username first, then first+last name
                user_id = None
                device_id = None
                if username and username != "unknown":
                    cur.execute(
                        "SELECT user_id, device_id FROM demo.users WHERE LOWER(username) = %s",
                        (username.lower(),),
                    )
                    row = cur.fetchone()
                    if row:
                        user_id, device_id = row[0], row[1]
                if user_id is None and first_name and last_name:
                    cur.execute(
                        "SELECT user_id, device_id FROM demo.users "
                        "WHERE LOWER(first_name) = %s AND LOWER(last_name) = %s",
                        (first_name.lower(), last_name.lower()),
                    )
                    row = cur.fetchone()
                    if row:
                        user_id, device_id = row[0], row[1]

                cur.execute(
                    """
                    INSERT INTO demo.tickets
                        (ticket_id, severity, status, assignment_group, user_id, device_id,
                         category, created_at, subject, description_text, ticket_type,
                         source_language)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticket_id) DO NOTHING
                    """,
                    (
                        str(ticket_id)[:20],
                        severity[:50] if severity else None,
                        status[:50] if status else None,
                        str(assignment_group)[:100] if assignment_group else None,
                        user_id,
                        device_id,
                        category[:100] if category else None,
                        created_at or None,
                        subject[:255] if subject else None,
                        description_text or None,
                        ticket_type[:50] if ticket_type else None,
                        source_language[:50] if source_language else None,
                    ),
                )
        logger.info("Ticket %s saved to demo.tickets.", ticket_id)
    except psycopg2.Error as e:
        logger.error("Failed to save ticket %s to demo.tickets: %s", ticket_id, e)


@mcp.tool
def create_ticket(
    issue: str,
    user: str = "unknown",
    category: str = "General",
    severity: str = "Medium",
    impacted_system: str = "Unknown",
    first_name: str = "",
    last_name: str = "",
    source_language: str = "",
    additional_cc_emails: list[str] | None = None,
) -> dict:
    """Create an IT support ticket in Freshworks.
    Provide 'user' (username) or 'first_name'+'last_name' to link the ticket to the correct user record.
    'additional_cc_emails' adds extra addresses to the CC list.
    """
    for field, val in [("issue", issue), ("user", user), ("category", category),
                       ("severity", severity), ("impacted_system", impacted_system),
                       ("first_name", first_name), ("last_name", last_name),
                       ("source_language", source_language)]:
        err = _guard(val, field)
        if err:
            return {"success": False, "error": err, "data": None}

    freshworks_api_key = os.getenv("FRESHWORKS_API_KEY", "")
    endpoint = _freshworks_endpoint()

    if not freshworks_api_key or not endpoint:
        return {
            "success": False,
            "error": "FRESHWORKS_API_KEY or FRESHWORKS_DOMAIN is not configured.",
            "data": None,
        }

    auth = base64.b64encode(f"{freshworks_api_key}:".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    requester_email, cc_emails, device_id = _resolve_requester_email(
        user=user, first_name=first_name, last_name=last_name,
        additional_cc_emails=additional_cc_emails,
    )

    # Translate to English if source language is not English
    ticket_issue = issue
    if source_language and source_language.strip().lower() != "english":
        ticket_issue = _translate_to_english(issue, source_language.strip())

    payload = {
        "email": requester_email,
        "cc_emails": cc_emails,
        "subject": ticket_issue[:100],
        "description": (
            f"Impacted System: {impacted_system}\nCategory: {category}\n"
            f"Source Language: {source_language.strip()}\n\n"
            f"Issue (English): {ticket_issue}\n\n"
            f"Original ({source_language.strip()}): {issue}"
        ) if source_language and source_language.strip().lower() != "english" else (
            f"Impacted System: {impacted_system}\nCategory: {category}\n\nIssue: {issue}"
        ),
        "status": 2,
        "priority": _map_severity_to_priority(severity),
        "urgency": _map_severity_to_scale3(severity),
        "impact": _map_severity_to_scale3(severity),
        "source": 2,
        "group_id": _map_category_to_group_id(category),
        "type": _map_category_to_ticket_type(category),
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if not response.ok:
            return {
                "success": False,
                "error": f"FreshWorks API error ({response.status_code}): {response.text}",
                "data": {"payload": payload},
            }

        ticket_data = response.json().get("ticket", {})
        freshworks_status = _map_freshworks_status(ticket_data.get("status"))
        freshworks_group  = ticket_data.get("group_id")

        # Persist to Postgres (non-fatal)
        _save_ticket_to_postgres(
            ticket_id=ticket_data.get("id"),
            severity=severity,
            status=freshworks_status,
            assignment_group=str(freshworks_group) if freshworks_group else None,
            username=user,
            first_name=first_name,
            last_name=last_name,
            category=category,
            created_at=ticket_data.get("created_at", ""),
            subject=ticket_data.get("subject", ""),
            description_text=ticket_data.get("description_text", ""),
            ticket_type=ticket_data.get("type", ""),
            source_language=source_language,
        )

        return {
            "success": True,
            "error": None,
            "data": {
                "ticket_id": ticket_data.get("id"),
                "ticket_number": ticket_data.get("ticket_number"),
                "user": user,
                "issue": issue,
                "category": category,
                "severity": severity,
                "impacted_system": impacted_system,
                "status": freshworks_status,
                "priority": _map_severity_to_priority(severity),
                "assignment_group": freshworks_group,
                "created_at_utc": ticket_data.get("created_at"),
                "url": f"https://{os.getenv('FRESHWORKS_DOMAIN')}.freshservice.com/support/tickets/{ticket_data.get('id')}",
            },
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"FreshWorks request failed: {e}",
            "data": None,
        }


@mcp.tool
def lookup_user(username: str = "", first_name: str = "", last_name: str = "") -> dict:
    """Look up a corporate user by username OR by first and last name (Postgres only)."""
    for field, val in [("username", username), ("first_name", first_name), ("last_name", last_name)]:
        if val:
            err = _guard(val, field)
            if err:
                return {"success": False, "error": err, "data": None}
    if not username and not (first_name and last_name):
        return {
            "success": False,
            "error": "Provide either 'username' or both 'first_name' and 'last_name'.",
            "data": None,
        }
    conn = _postgres_conn_string()
    if not conn:
        return {"success": False, "error": "AZURE_POSTGRESQL_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn) as connection:
            with connection.cursor() as cursor:
                if username:
                    cursor.execute(
                        "SELECT username, first_name, last_name, department, email, device_id "
                        "FROM demo.users WHERE LOWER(username) = %s",
                        (username.lower(),),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return {"success": False, "error": f"No user found for username '{username}'.", "data": None}
                    return {
                        "success": True,
                        "error": None,
                        "data": {
                            "username": row[0],
                            "first_name": row[1],
                            "last_name": row[2],
                            "department": row[3],
                            "email": row[4],
                            "device_id": row[5],
                        },
                    }
                else:
                    cursor.execute(
                        "SELECT username, first_name, last_name, department, email, device_id "
                        "FROM demo.users "
                        "WHERE LOWER(first_name) = %s AND LOWER(last_name) = %s",
                        (first_name.lower(), last_name.lower()),
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        return {"success": False, "error": f"No user found for name '{first_name} {last_name}'.", "data": None}
                    matches = [
                        {
                            "username": r[0],
                            "first_name": r[1],
                            "last_name": r[2],
                            "department": r[3],
                            "email": r[4],
                            "device_id": r[5],
                        }
                        for r in rows
                    ]
                    return {
                        "success": True,
                        "error": None,
                        "count": len(matches),
                        "data": matches,
                    }
    except psycopg2.Error as e:
        return {"success": False, "error": f"Database error: {e}", "data": None}


@mcp.tool
def lookup_ticket(ticket_id: str) -> dict:
    """Look up ticket details from demo.tickets joined with demo.users for requester contact info."""
    if not ticket_id or not ticket_id.strip():
        return {"success": False, "error": "Provide a ticket_id.", "data": None}
    err = _guard(ticket_id, "ticket_id")
    if err:
        return {"success": False, "error": err, "data": None}
    conn_str = _postgres_conn_string()
    if not conn_str:
        return {"success": False, "error": "AZURE_POSTGRESQL_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.ticket_id, t.severity, t.status, t.assignment_group,
                           t.category, t.created_at, t.subject, t.description_text, t.ticket_type,
                           u.first_name, u.last_name, u.email
                    FROM demo.tickets t
                    LEFT JOIN demo.users u ON u.user_id = t.user_id
                    WHERE t.ticket_id = %s
                    """,
                    (ticket_id.strip(),),
                )
                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": f"No ticket found with ID '{ticket_id}'.", "data": None}
                return {
                    "success": True,
                    "error": None,
                    "data": {
                        "ticket_id": row[0],
                        "severity": row[1],
                        "status": row[2],
                        "assignment_group": row[3],
                        "category": row[4],
                        "created_at": str(row[5]) if row[5] else None,
                        "subject": row[6],
                        "description_text": row[7],
                        "ticket_type": row[8],
                        "first_name": row[9],
                        "last_name": row[10],
                        "email": row[11],
                    },
                }
    except psycopg2.Error as e:
        return {"success": False, "error": f"Database error: {e}", "data": None}


@mcp.tool
def lookup_tickets_by_user(username: str = "", first_name: str = "", last_name: str = "") -> dict:
    """Look up all support tickets for a user by username OR first and last name."""
    username = (username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    for field, val in [("username", username), ("first_name", first_name), ("last_name", last_name)]:
        if val:
            err = _guard(val, field)
            if err:
                return {"success": False, "error": err, "data": None}
    if not username and not (first_name and last_name):
        return {"success": False, "error": "Provide a username or both first_name and last_name.", "data": None}
    conn_str = _postgres_conn_string()
    if not conn_str:
        return {"success": False, "error": "AZURE_POSTGRESQL_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn_str) as conn:
            with conn.cursor() as cur:
                conditions = []
                params = []
                if username:
                    conditions.append("u.username = %s")
                    params.append(username)
                if first_name and last_name:
                    conditions.append("(u.first_name ILIKE %s AND u.last_name ILIKE %s)")
                    params.extend([first_name, last_name])
                where_clause = " OR ".join(conditions)
                cur.execute(
                    f"""
                    SELECT t.ticket_id, t.severity, t.status, t.assignment_group,
                           t.category, t.created_at, t.subject, t.description_text, t.ticket_type,
                           u.first_name, u.last_name, u.email, u.username
                    FROM demo.tickets t
                    LEFT JOIN demo.users u ON u.user_id = t.user_id
                    WHERE {where_clause}
                    ORDER BY t.created_at DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
                if not rows:
                    return {"success": False, "error": "No tickets found for that user.", "data": None}
                tickets = [
                    {
                        "ticket_id": r[0],
                        "severity": r[1],
                        "status": r[2],
                        "assignment_group": r[3],
                        "category": r[4],
                        "created_at": str(r[5]) if r[5] else None,
                        "subject": r[6],
                        "description_text": r[7],
                        "ticket_type": r[8],
                        "first_name": r[9],
                        "last_name": r[10],
                        "email": r[11],
                        "username": r[12],
                    }
                    for r in rows
                ]
                return {"success": True, "error": None, "data": tickets}
    except psycopg2.Error as e:
        return {"success": False, "error": f"Database error: {e}", "data": None}


@mcp.tool
def check_device_status(
    device_or_username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """Check device state by device ID, username, or first and last name (Postgres only).
    Provide 'device_or_username' for a device ID or username lookup, or provide both
    'first_name' and 'last_name' to look up by the user's full name.
    """
    device_or_username = (device_or_username or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()

    for field, val in [("device_or_username", device_or_username),
                       ("first_name", first_name), ("last_name", last_name)]:
        if val:
            err = _guard(val, field)
            if err:
                return {"success": False, "error": err, "data": None}

    if not device_or_username and not (first_name and last_name):
        return {
            "success": False,
            "error": "Provide a device ID or username via 'device_or_username', or provide both 'first_name' and 'last_name'.",
            "data": None,
        }

    conn = _postgres_conn_string()
    if not conn:
        return {"success": False, "error": "AZURE_POSTGRESQL_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn) as connection:
            with connection.cursor() as cursor:
                conditions = []
                params = []

                if device_or_username:
                    conditions.append("UPPER(d.device_id) = UPPER(%s)")
                    params.append(device_or_username)
                    conditions.append("LOWER(u.username) = LOWER(%s)")
                    params.append(device_or_username)

                if first_name and last_name:
                    conditions.append("(LOWER(u.first_name) = LOWER(%s) AND LOWER(u.last_name) = LOWER(%s))")
                    params.extend([first_name, last_name])

                where_clause = " OR ".join(conditions)
                cursor.execute(
                    f"""
                    SELECT d.device_id, d.status, d.vpn_client, d.last_seen, u.username,
                           u.first_name, u.last_name
                    FROM demo.devices d
                    LEFT JOIN demo.users u ON u.device_id = d.device_id
                    WHERE {where_clause}
                    LIMIT 1
                    """,
                    params,
                )
                row = cursor.fetchone()
                if not row:
                    identifier = device_or_username or f"{first_name} {last_name}"
                    return {"success": False, "error": f"No device found for identifier '{identifier}'.", "data": None}
                return {
                    "success": True,
                    "error": None,
                    "data": {
                        "device_id": row[0],
                        "status": row[1],
                        "vpn_client": row[2],
                        "last_seen": str(row[3]),
                        "username": row[4] or "unknown",
                        "first_name": row[5] or "",
                        "last_name": row[6] or "",
                    },
                }
    except psycopg2.Error as e:
        return {"success": False, "error": f"Database error: {e}", "data": None}


# To run:
#   python mcp_server.py                          (stdio transport)
# To run:
#   python mcp_server.py                          (STDIO - for Inspector)
#   python mcp_server.py --http                   (HTTP transport on port 8000)
#   fastmcp run mcp_server.py:mcp --transport http --port 8000  (HTTP via CLI)
#   npx @modelcontextprotocol/inspector python mcp_server.py    (MCP Inspector)

if __name__ == "__main__":
    import sys
    if "--http" in sys.argv:
        mcp_host = os.getenv("MCP_BIND_HOST", "127.0.0.1")
        mcp_port = int(os.getenv("MCP_PORT", "8000"))
        mcp.run(transport="http", host=mcp_host, port=mcp_port)
    else:
        mcp.run()  # STDIO transport (default, works with Inspector)
