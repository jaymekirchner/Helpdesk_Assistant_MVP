"""Azure AI Search retrieval and query enrichment."""

import re

from config.settings import openai_client, search_client, OPENAI_DEPLOYMENT
from config.constants import HISTORY_LIMIT
from prompts.orchestrator import RETRIEVAL_QUERY_BUILDER_SYSTEM


class RetrievalEngine:
    """Handles search-query enrichment and Azure AI Search document retrieval."""

    def __init__(self):
        self._openai = openai_client
        self._search = search_client

    # ── Query enrichment ─────────────────────────────────────────────────────

    def build_retrieval_query(self, user_input: str, conversation_history: list) -> str:
        if not conversation_history:
            print(f"[DEBUG] No history — using raw query: {user_input}")
            return user_input

        messages = [
            {"role": "system", "content": RETRIEVAL_QUERY_BUILDER_SYSTEM},
            *conversation_history[-HISTORY_LIMIT:],
            {"role": "user", "content": user_input},
        ]

        try:
            response = self._openai.chat.completions.create(
                model=OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=0,
                max_tokens=50,
            )
            enriched_query = response.choices[0].message.content.strip()
            print(f"[DEBUG] Enriched retrieval query: '{enriched_query}'")
            return enriched_query
        except Exception as e:
            print(f"[DEBUG] Query enrichment failed: {e} — falling back to raw input")
            return user_input

    # ── Document retrieval ───────────────────────────────────────────────────

    def get_search_results(self, query: str, top_k: int = 5) -> list[str]:
        try:
            results = self._search.search(query, top=top_k)
            docs = []
            for doc in results:
                for field in ["content", "text", "chunk", "chunk_text"]:
                    if field in doc and doc[field]:
                        docs.append(doc[field])
                        break
                else:
                    docs.append(str(doc))
            return docs
        except Exception as e:
            print(f"Error querying Azure Search: {e}")
            return []

    # ── Error-code helpers ───────────────────────────────────────────────────

    @staticmethod
    def extract_error_code(text: str) -> str | None:
        match = re.search(
            r"\b(?:error(?:\s+code)?\s*)?(0x[0-9A-Fa-f]+|\d{3,6})\b",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).lower() if match else None

    @staticmethod
    def docs_contain_error_code(docs: list[str], error_code: str) -> bool:
        if not error_code:
            return False
        return any(error_code in doc.lower() for doc in docs)
