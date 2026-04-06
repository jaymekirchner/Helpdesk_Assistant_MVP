"""Application settings: environment variables, client initialization, startup checks."""

import os
import sys

from dotenv import load_dotenv
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

# ── Azure AI Search ──────────────────────────────────────────────────────────
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

# ── Azure OpenAI ─────────────────────────────────────────────────────────────
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# ── MCP ──────────────────────────────────────────────────────────────────────
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")
MCP_MAX_RETRIES = 3
MCP_RETRY_BACKOFF = [0.5, 1.5, 3.0]

# ── Startup diagnostics ─────────────────────────────────────────────────────
_MISSING_STARTUP_VARS = [
    name for name, value in {
        "AZURE_SEARCH_ENDPOINT": SEARCH_ENDPOINT,
        "AZURE_SEARCH_KEY": SEARCH_KEY,
        "AZURE_SEARCH_INDEX": SEARCH_INDEX,
        "AZURE_OPENAI_ENDPOINT": OPENAI_ENDPOINT,
        "AZURE_OPENAI_API_KEY": OPENAI_KEY,
        "AZURE_OPENAI_DEPLOYMENT": OPENAI_DEPLOYMENT,
    }.items()
    if not value
]

if _MISSING_STARTUP_VARS:
    print(
        "[Startup Warning] Missing environment variables: "
        + ", ".join(_MISSING_STARTUP_VARS)
        + ". App will start in degraded mode."
    )

# ── Client singletons ───────────────────────────────────────────────────────
search_client = None
if SEARCH_ENDPOINT and SEARCH_KEY and SEARCH_INDEX:
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX,
        credential=AzureKeyCredential(SEARCH_KEY),
    )

openai_client = None
if OPENAI_ENDPOINT and OPENAI_KEY and OPENAI_DEPLOYMENT:
    openai_client = AzureOpenAI(
        api_key=OPENAI_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=OPENAI_ENDPOINT,
    )
