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


def _resolve_requester_email(user: str) -> str:
    default_email = os.getenv("FRESHWORKS_DEFAULT_REQUESTER_EMAIL", "helpdesk@corp.com")
    if user and "@" in user:
        return user
    return default_email


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
) -> None:
    """Persist ticket details to demo.tickets. Resolves user_id and device_id from demo.users.
    Tries username first; falls back to first_name + last_name if username is missing or not found.
    Non-fatal: logs errors but never raises so ticket creation always succeeds."""
    conn_str = _postgres_conn_string()
    if not conn_str:
        print("[Postgres] Connection string not configured — skipping ticket save.")
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
                        (ticket_id, severity, status, assignment_group, user_id, device_id, update_timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticket_id) DO UPDATE SET
                        severity         = EXCLUDED.severity,
                        status           = EXCLUDED.status,
                        assignment_group = EXCLUDED.assignment_group,
                        user_id          = EXCLUDED.user_id,
                        device_id        = EXCLUDED.device_id,
                        update_timestamp = EXCLUDED.update_timestamp
                    """,
                    (
                        str(ticket_id)[:20],
                        severity[:50] if severity else None,
                        status[:50] if status else None,
                        str(assignment_group)[:100] if assignment_group else None,
                        user_id,
                        device_id,
                        datetime.datetime.utcnow(),
                    ),
                )
        print(f"[Postgres] Ticket {ticket_id} saved to demo.tickets.")
    except psycopg2.Error as e:
        print(f"[Postgres] Failed to save ticket {ticket_id} to demo.tickets: {e}")


@mcp.tool
def create_ticket(
    issue: str,
    user: str = "unknown",
    category: str = "General",
    severity: str = "Medium",
    impacted_system: str = "Unknown",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """Create an IT support ticket in Freshworks.
    Provide 'user' (username) or 'first_name'+'last_name' to link the ticket to the correct user record.
    """
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
def check_device_status(device_or_username: str) -> dict:
    """Check device state by device ID or username (Postgres only)."""
    conn = _postgres_conn_string()
    if not conn:
        return {"success": False, "error": "AZURE_POSTGRESQL_CONNECTION_STRING is not configured.", "data": None}
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
        mcp_host = os.getenv("MCP_BIND_HOST", "127.0.0.1")
        mcp_port = int(os.getenv("MCP_PORT", "8000"))
        mcp.run(transport="http", host=mcp_host, port=mcp_port)
    else:
        mcp.run()  # STDIO transport (default, works with Inspector)
