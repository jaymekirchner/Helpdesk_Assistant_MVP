"""Custom evaluator: Tool Selection Accuracy.

Measures whether the ActionAgent called the single correct MCP tool for a given
user query.  The evaluation is fully deterministic (no LLM judge required).

Expected dataset columns
------------------------
query          : str   — the raw user message sent to the ActionAgent
expected_tool  : str   — the single correct tool name (e.g. "lookup_user")
tool_calls     : str   — JSON-encoded list of tool names actually invoked by
                         the agent during the run (populated by runner.py)

Output columns
--------------
tool_selection_accuracy        : float  — 1.0 if expected_tool is in tool_calls,
                                          0.0 otherwise
tool_selection_accuracy_reason : str    — human-readable explanation
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolSelectionAccuracyEvaluator:
    """Deterministic evaluator for ActionAgent tool selection.

    Compatible with ``azure.ai.evaluation.evaluate()`` custom evaluator protocol:
    the class must expose ``id`` and be callable with keyword arguments that map
    to dataset columns (configured via ``evaluator_config``).
    """

    # Stable identifier used by Azure AI Foundry to track this evaluator across runs.
    id = "tool_selection_accuracy"

    # All valid tool names registered in agents/tool_registry.py
    VALID_TOOLS: frozenset[str] = frozenset(
        {
            "lookup_user",
            "check_device_status",
            "create_ticket",
            "lookup_ticket",
            "lookup_tickets_by_user",
        }
    )

    def __call__(
        self,
        *,
        query: str,
        expected_tool: str,
        tool_calls: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Score a single test case.

        Parameters
        ----------
        query:
            The user message that was sent to the agent (for logging/context).
        expected_tool:
            The single tool name that should have been invoked.
        tool_calls:
            Either a JSON string or a Python list of tool names that were
            actually called by the agent during the run.

        Returns
        -------
        dict with keys:
            ``tool_selection_accuracy``        float in {0.0, 1.0}
            ``tool_selection_accuracy_reason`` human-readable explanation
        """
        # ── Normalise tool_calls ─────────────────────────────────────────────
        if isinstance(tool_calls, str):
            try:
                called: list[str] = json.loads(tool_calls)
            except (json.JSONDecodeError, ValueError):
                # Treat a bare tool name as a single-item list.
                called = [tool_calls.strip()] if tool_calls.strip() else []
        elif isinstance(tool_calls, list):
            called = [str(t) for t in tool_calls]
        else:
            called = []

        # ── Normalise expected_tool ──────────────────────────────────────────
        expected_tool = (expected_tool or "").strip()
        if expected_tool not in self.VALID_TOOLS:
            logger.warning(
                "ToolSelectionAccuracyEvaluator: expected_tool '%s' is not in the "
                "known tool set %s — check your dataset.",
                expected_tool,
                sorted(self.VALID_TOOLS),
            )

        # ── Score ────────────────────────────────────────────────────────────
        hit = expected_tool in called
        score = 1.0 if hit else 0.0

        if hit:
            reason = (
                f"PASS — agent correctly called '{expected_tool}'. "
                f"Full tool call sequence: {called}."
            )
        elif not called:
            reason = (
                f"FAIL — agent made NO tool calls. "
                f"Expected '{expected_tool}'."
            )
        else:
            reason = (
                f"FAIL — agent called {called} but expected '{expected_tool}'. "
                f"Possible mis-routing by TriageAgent or incorrect tool selection by ActionAgent."
            )

        logger.debug(
            "tool_selection_accuracy | query=%r expected=%r called=%r score=%.1f",
            query[:80],
            expected_tool,
            called,
            score,
        )

        return {
            "tool_selection_accuracy": score,
            "tool_selection_accuracy_reason": reason,
        }
