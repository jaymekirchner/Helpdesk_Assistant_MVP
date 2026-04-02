# mcp_server.py
from mcp.server.fastmcp import FastMCP
from typing import *
from old_files.app5_ma_experimental import *
import requests

mcp = FastMCP("Pod2")
# Add a resource
@mcp.resource("greeting://{name}")

def get_greeting(name: str) -> str:
    """Get a personalized greeting."""
    return f"Hello, {name}!"

# Add a prompt
@mcp.prompt()
def review_prompt(code: str) -> str:
    """Generate a code review prompt."""
    return f"Please review this code:\n\n{code}"



@mcp.tool()
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
if __name__ == "__main__":
    pass


@mcp.tool()
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

@mcp.tool()
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
    try:
        response = requests.post(POST_URL, json=record)
        if response.status_code == 200:
            pass
        else:
            print(f"{response.status_code} [DEBUG] Failed to post ticket {ticket_id}: {response.text}")
    except Exception as e:
        print(f"[DEBUG] Error posting ticket {ticket_id}: {e}")

    return (f"{response.status_code} [DEBUG] Ticket {ticket_id} posted successfully to {POST_URL}"
        f"Ticket created successfully.\n"
        f"- Ticket ID: {ticket_id}\n"
        f"- User: {user}\n"
        f"- Issue: {issue}\n"
        f"- Category: {category}\n"
        f"- Severity: {severity}\n"
        f"- Impacted System: {impacted_system}\n"
        f"- Status: Open\n"
        f"- Assignment Group: IT Service Desk"
    )


def _write_ticket(ticket_record):
    with TICKETS_FILE.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(ticket_record) + "\n")


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
