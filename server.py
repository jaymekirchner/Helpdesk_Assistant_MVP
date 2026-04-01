from mcp.server.fastmcp import FastMCP
# from app5_ma_experimental import *

# Initialize the FastMCP server
mcp = FastMCP("MyPythonServer")

# Define a tool that the LLM can call
@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Adds two numbers together."""
    return a + b

# Define a resource (e.g., a dynamic greeting)
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Returns a personalized greeting."""
    return f"Hello, {name}! Welcome to the MCP server."

if __name__ == "__main__":
    # Run the server using the standard input/output transport
    mcp.run(transport="stdio")