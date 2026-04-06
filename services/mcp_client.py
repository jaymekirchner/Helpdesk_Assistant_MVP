"""MCP client — calls MCP tools over HTTP transport with retry/backoff."""

import asyncio
import json
import time
import concurrent.futures

from config.settings import MCP_SERVER_URL, MCP_MAX_RETRIES, MCP_RETRY_BACKOFF


class MCPClient:
    """Wraps fastmcp.Client to call MCP tools with automatic retry."""

    def __init__(self, server_url: str | None = None):
        self._url = server_url or MCP_SERVER_URL

    def call_tool(self, tool_name: str, args: dict):
        from fastmcp import Client

        async def _call_async():
            client = Client(self._url)
            async with client:
                return await client.call_tool(tool_name, args)

        last_exc = None
        for attempt in range(MCP_MAX_RETRIES):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _call_async()).result()
            except Exception as e:
                last_exc = e
                if attempt < MCP_MAX_RETRIES - 1:
                    delay = MCP_RETRY_BACKOFF[attempt]
                    print(f"[MCP] Tool '{tool_name}' attempt {attempt + 1} failed: {e} — retrying in {delay}s")
                    time.sleep(delay)
                else:
                    print(f"[MCP] Tool '{tool_name}' failed after {MCP_MAX_RETRIES} attempts: {e}")
        raise last_exc

    @staticmethod
    def extract_records(result) -> list[dict]:
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


# Module-level singleton
mcp_client = MCPClient()
