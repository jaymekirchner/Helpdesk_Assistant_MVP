from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

# Import tool implementations directly from app5_orig
from app5_orig import (
    lookup_user as _lookup_user,
    check_device_status as _check_device_status,
    create_ticket as _create_ticket,
    search_knowledge_base as _search_knowledge_base,
)

mcp = FastMCP("Pod2")


@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting."""
    return f"Hello, {name}!"


@mcp.prompt()
def review_prompt(code: str) -> str:
    """Generate a code review prompt."""
    return f"Please review this code:\n\n{code}"


@mcp.tool()
def lookup_user(
    username: Annotated[str, Field(description="Employee username, for example jdoe")]
) -> str:
    """Look up a corporate user by username."""
    return _lookup_user(username)


@mcp.tool()
def check_device_status(
    device_id: Annotated[str, Field(description="Device ID, for example LAPTOP-1001")]
) -> str:
    """Check the status of a company device by device ID."""
    return _check_device_status(device_id)


@mcp.tool()
def create_ticket(
    issue: Annotated[str, Field(description="The unresolved IT issue")],
    user: Annotated[str, Field(description="Username or identifier of the user")] = "unknown",
    category: Annotated[str, Field(description="Issue category such as VPN, Email, MFA, Device")] = "General",
    severity: Annotated[str, Field(description="Business impact severity: Low, Medium, High, Critical")] = "Medium",
    impacted_system: Annotated[str, Field(description="Impacted application or system")] = "Unknown",
) -> str:
    """Create an IT support ticket when the issue is unresolved or the user asks to open a ticket."""
    return _create_ticket(
        issue=issue,
        user=user,
        category=category,
        severity=severity,
        impacted_system=impacted_system,
    )


@mcp.tool()
def search_knowledge_base(
    query: Annotated[str, Field(description="Concise keyword search query describing the IT issue")]
) -> str:
    """Search the IT knowledge base for troubleshooting steps and known solutions."""
    return _search_knowledge_base(query)


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
