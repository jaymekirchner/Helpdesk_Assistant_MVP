import os
import base64
import datetime

import psycopg2
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("IT Helpdesk MCP Server")


@mcp.tool
def health_check() -> dict:
    """Return server readiness status and connectivity checks for all dependencies."""
    checks = {}

    # Postgres
    conn_str = _postgres_conn_string()
    if conn_str:
        try:
            with psycopg2.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            checks["postgres"] = "ok"
        except psycopg2.Error as e:
            checks["postgres"] = f"error: {e}"
    else:
        checks["postgres"] = "not configured"

    # Freshworks
    if os.getenv("FRESHWORKS_API_KEY") and os.getenv("FRESHWORKS_DOMAIN"):
        checks["freshworks"] = "configured"
    else:
        checks["freshworks"] = "not configured"

    all_ok = all(v in ("ok", "configured") for v in checks.values())
    return {
        "success": all_ok,
        "error": None if all_ok else "One or more dependencies are unavailable",
        "data": {
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
            "timestamp_utc": datetime.datetime.utcnow().isoformat(),
        },
    }


def _postgres_conn_string() -> str:
    return os.getenv("POSTGRES_CONNECTION_STRING", "")


def _freshworks_endpoint() -> str:
    domain = os.getenv("FRESHWORKS_DOMAIN", "")
    if not domain:
        return ""
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


def _resolve_requester_email(user: str) -> str:
    default_email = os.getenv("FRESHWORKS_DEFAULT_REQUESTER_EMAIL", "helpdesk@corp.com")
    if user and "@" in user:
        return user
    return default_email


@mcp.tool
def create_ticket(
    issue: str,
    user: str = "unknown",
    category: str = "General",
    severity: str = "Medium",
    impacted_system: str = "Unknown",
) -> dict:
    """Create an IT support ticket in Freshworks."""
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

    payload = {
        "email": _resolve_requester_email(user),
        "subject": issue[:100],
        "description": f"Impacted System: {impacted_system}\nCategory: {category}\n\nIssue: {issue}",
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
                "status": ticket_data.get("status"),
                "priority": _map_severity_to_priority(severity),
                "assignment_group": ticket_data.get("group_id"),
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
def lookup_user(username: str) -> dict:
    """Look up a corporate user by username (Postgres only)."""
    conn = _postgres_conn_string()
    if not conn:
        return {"success": False, "error": "POSTGRES_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT username, first_name, last_name, department, email, device_id FROM demo.users WHERE LOWER(username) = %s",
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
    except psycopg2.Error as e:
        return {"success": False, "error": f"Database error: {e}", "data": None}


@mcp.tool
def check_device_status(device_or_username: str) -> dict:
    """Check device state by device ID or username (Postgres only)."""
    conn = _postgres_conn_string()
    if not conn:
        return {"success": False, "error": "POSTGRES_CONNECTION_STRING is not configured.", "data": None}
    try:
        with psycopg2.connect(conn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.device_id, d.status, d.vpn_client, d.last_seen, u.username
                    FROM demo.devices d
                    LEFT JOIN demo.users u ON u.device_id = d.device_id
                    WHERE UPPER(d.device_id) = UPPER(%s)
                       OR LOWER(u.username) = LOWER(%s)
                    LIMIT 1
                    """,
                    (device_or_username, device_or_username),
                )
                row = cursor.fetchone()
                if not row:
                    return {"success": False, "error": f"No device found for identifier '{device_or_username}'.", "data": None}
                return {
                    "success": True,
                    "error": None,
                    "data": {
                        "device_id": row[0],
                        "status": row[1],
                        "vpn_client": row[2],
                        "last_seen": str(row[3]),
                        "username": row[4] or "unknown",
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
        mcp.run(transport="http", host="0.0.0.0", port=8000)
    else:
        mcp.run()  # STDIO transport (default, works with Inspector)
