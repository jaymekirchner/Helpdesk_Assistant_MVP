"""MCP client — calls MCP tools over HTTP transport with retry/backoff."""

import asyncio
import json
import logging
import time
import concurrent.futures

from config.settings import MCP_SERVER_URL, MCP_MAX_RETRIES, MCP_RETRY_BACKOFF

logger = logging.getLogger(__name__)


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
                    logger.warning("Tool '%s' attempt %d failed: %s — retrying in %ss", tool_name, attempt + 1, e, delay)
                    time.sleep(delay)
                else:
                    logger.error("Tool '%s' failed after %d attempts: %s", tool_name, MCP_MAX_RETRIES, e)
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
