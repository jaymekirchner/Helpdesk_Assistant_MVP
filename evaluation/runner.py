"""Evaluation runner for the IT Helpdesk Agent.

Generates two JSONL result files consumed by run_eval.py:

1. evaluation/results/tool_selection_results.jsonl
   Sends each test query to the real ActionAgent with the MCP server
   monkey-patched so no live MCP connection is needed.  Records which tool
   names the LLM actually invoked alongside the expected tool.

2. evaluation/results/escalation_results.jsonl
   Runs the real EscalationService on each mock_response from the
   escalation dataset so the evaluator can compare the decision against
   the expected_escalation ground-truth flag.

Usage (standalone)
------------------
    python -m evaluation.runner                  # both datasets
    python -m evaluation.runner --tool           # tool-selection only
    python -m evaluation.runner --escalation     # escalation only
    python -m evaluation.runner --verbose        # with INFO logs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import MagicMock, patch

# ── Path setup ───────────────────────────────────────────────────────────────
_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(__file__)
DATASETS_DIR = os.path.join(_HERE, "datasets")
RESULTS_DIR = os.path.join(_HERE, "results")

TOOL_SELECTION_DATASET = os.path.join(DATASETS_DIR, "tool_selection_test_cases.jsonl")
ESCALATION_DATASET = os.path.join(DATASETS_DIR, "escalation_test_cases.jsonl")

TOOL_SELECTION_RESULTS = os.path.join(RESULTS_DIR, "tool_selection_results.jsonl")
ESCALATION_RESULTS = os.path.join(RESULTS_DIR, "escalation_results.jsonl")

# ── Mock MCP responses ────────────────────────────────────────────────────────
# Realistic-enough stub payloads so the LLM agent can process the tool result
# and form a coherent reply.

_MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "lookup_user": {
        "success": True,
        "count": 1,
        "data": {
            "username": "test.user",
            "first_name": "Test",
            "last_name": "User",
            "department": "IT Operations",
            "email": "test.user@company.com",
            "device_id": "LAPTOP-EVAL01",
        },
    },
    "check_device_status": {
        "success": True,
        "data": {
            "device_id": "LAPTOP-EVAL01",
            "username": "test.user",
            "status": "Active",
            "vpn_client": "Cisco AnyConnect 4.10",
            "last_seen": "2026-04-07T08:00:00Z",
        },
    },
    "create_ticket": {
        "success": True,
        "data": {
            "ticket_id": "TKT-EVAL001",
            "status": "Open",
            "priority": "Medium",
            "assignment_group": "IT Support L1",
        },
    },
    "lookup_ticket": {
        "success": True,
        "data": {
            "ticket_id": "TKT-12345",
            "subject": "Evaluation test ticket",
            "status": "Open",
            "severity": "Medium",
            "category": "General",
            "ticket_type": "Incident",
            "assignment_group": "IT Support L1",
            "created_at": "2026-04-01T09:00:00Z",
            "first_name": "Test",
            "last_name": "User",
            "email": "test.user@company.com",
        },
    },
    "lookup_tickets_by_user": {
        "success": True,
        "data": [
            {
                "ticket_id": "TKT-22222",
                "subject": "Evaluation test ticket list",
                "status": "Closed",
                "severity": "Low",
                "category": "Software",
                "ticket_type": "Request",
                "assignment_group": "Desktop Support",
                "created_at": "2026-03-15T14:00:00Z",
                "first_name": "Test",
                "last_name": "User",
                "email": "test.user@company.com",
            }
        ],
    },
}


def _make_mock_mcp_call_result(tool_name: str):
    """Return a fake fastmcp CallToolResult for the given tool."""
    payload = _MOCK_RESPONSES.get(tool_name, {"success": False, "error": "Unknown tool"})

    class _TextContent:
        def __init__(self, text: str):
            self.text = text

    class _FakeResult:
        def __init__(self, text: str):
            self.content = [_TextContent(text)]

    return _FakeResult(json.dumps(payload))


@contextmanager
def _patch_mcp(captured_calls: list[str]) -> Generator[None, None, None]:
    """Context manager that replaces ``mcp_client.call_tool`` with a stub.

    Every call is recorded in ``captured_calls`` (by tool name), and a
    realistic mock result is returned so the agent can finish its turn.
    """

    original_call = None

    def _mock_call_tool(tool_name: str, args: dict) -> Any:
        logger.debug("  [mock MCP] call_tool('%s', %s)", tool_name, args)
        captured_calls.append(tool_name)
        return _make_mock_mcp_call_result(tool_name)

    # Patch both the module-level singleton and the class method path.
    with patch("services.mcp_client.mcp_client.call_tool", side_effect=_mock_call_tool):
        with patch(
            "agents.tool_registry.mcp_client.call_tool", side_effect=_mock_call_tool
        ):
            yield


# ── Tool selection runner ─────────────────────────────────────────────────────


async def _run_single_tool_case(
    test_case: dict[str, Any],
) -> dict[str, Any]:
    """Run one tool-selection test case, return the enriched result dict."""
    # Import here so patching is in effect when these modules initialise.
    from agents.agent_factory import action_agent  # noqa: PLC0415

    query: str = test_case["query"]
    expected_tool: str = test_case["expected_tool"]

    captured: list[str] = []
    response_text: str = ""
    error_msg: str = ""

    if action_agent is None:
        error_msg = "ActionAgent unavailable (check Azure OpenAI env vars)"
        logger.warning("Skipping query %r — %s", query, error_msg)
    else:
        try:
            with _patch_mcp(captured):
                result = await action_agent.run(query)
                response_text = result.text.strip() if result and result.text else ""
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("ActionAgent run failed for query %r: %s", query, exc)

    return {
        "query": query,
        "expected_tool": expected_tool,
        "tool_calls": json.dumps(captured),
        "response": response_text,
        "error": error_msg,
    }


async def run_tool_selection_runner(
    dataset_path: str = TOOL_SELECTION_DATASET,
    output_path: str = TOOL_SELECTION_RESULTS,
    delay_between_calls: float = 1.0,
) -> str:
    """Run all tool-selection test cases and write results JSONL.

    Returns the output file path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(dataset_path, encoding="utf-8") as fh:
        test_cases = [json.loads(line) for line in fh if line.strip()]

    print(
        f"\n[Runner] Tool Selection — {len(test_cases)} test cases → {output_path}"
    )

    results: list[dict] = []
    for i, tc in enumerate(test_cases, 1):
        print(f"  [{i:02d}/{len(test_cases)}] {tc['query'][:70]}")
        result = await _run_single_tool_case(tc)

        called = json.loads(result["tool_calls"])
        status_icon = "✓" if tc["expected_tool"] in called else "✗"
        print(
            f"         {status_icon} expected={tc['expected_tool']}  "
            f"actual={called or ['(none)']}"
        )
        results.append(result)

        if i < len(test_cases):
            await asyncio.sleep(delay_between_calls)

    with open(output_path, "w", encoding="utf-8") as fh:
        for record in results:
            fh.write(json.dumps(record) + "\n")

    hits = sum(
        1 for r in results if r["expected_tool"] in json.loads(r["tool_calls"])
    )
    print(
        f"\n[Runner] Tool Selection complete — {hits}/{len(results)} correct "
        f"({100 * hits / max(len(results), 1):.1f}% raw accuracy)\n"
    )
    return output_path


# ── Escalation runner ─────────────────────────────────────────────────────────


def run_escalation_runner(
    dataset_path: str = ESCALATION_DATASET,
    output_path: str = ESCALATION_RESULTS,
) -> str:
    """Run EscalationService on every mock response and write results JSONL.

    Returns the output file path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Import after path setup so project modules resolve correctly.
    from services.escalation_service import EscalationService  # noqa: PLC0415

    esc_service = EscalationService()

    with open(dataset_path, encoding="utf-8") as fh:
        test_cases = [json.loads(line) for line in fh if line.strip()]

    print(
        f"[Runner] Escalation — {len(test_cases)} test cases → {output_path}"
    )

    results: list[dict] = []
    for i, tc in enumerate(test_cases, 1):
        mock_resp: str = tc.get("mock_response", "")
        expected: bool = bool(tc.get("expected_escalation", False))

        # Run the actual EscalationService logic.
        if esc_service.should_run_escalation_check(mock_resp):
            processed_resp = esc_service.check_escalation(mock_resp)
        else:
            # Responses that clearly don't contain the KB-miss trigger still
            # go through the LLM uncertainty check.
            processed_resp = esc_service.check_escalation(mock_resp)

        from config.constants import ESCALATION_SUFFIX  # noqa: PLC0415

        actual_escalated = ESCALATION_SUFFIX.strip() in processed_resp
        status_icon = "✓" if actual_escalated == expected else "✗"
        print(
            f"  [{i:02d}/{len(test_cases)}] {status_icon} "
            f"expected={'ESC' if expected else 'NO_ESC':10s}  "
            f"actual={'ESC' if actual_escalated else 'NO_ESC':10s}  "
            f"{tc['query'][:50]}"
        )

        results.append(
            {
                "query": tc["query"],
                "response": processed_resp,
                "expected_escalation": expected,
            }
        )

    with open(output_path, "w", encoding="utf-8") as fh:
        for record in results:
            fh.write(json.dumps(record) + "\n")

    hits = sum(
        1
        for r in results
        if (ESCALATION_SUFFIX.strip() in r["response"]) == r["expected_escalation"]
    )
    print(
        f"\n[Runner] Escalation complete — {hits}/{len(results)} correct "
        f"({100 * hits / max(len(results), 1):.1f}% raw accuracy)\n"
    )
    return output_path


# ── CLI entry-point ───────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate evaluation result files for the Helpdesk Agent."
    )
    parser.add_argument(
        "--tool", action="store_true", help="Run tool-selection runner only."
    )
    parser.add_argument(
        "--escalation", action="store_true", help="Run escalation runner only."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between ActionAgent calls (default: 1.0).",
    )
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> None:
    run_tool = args.tool or not args.escalation
    run_esc = args.escalation or not args.tool

    if run_esc:
        run_escalation_runner()

    if run_tool:
        await run_tool_selection_runner(delay_between_calls=args.delay)


if __name__ == "__main__":
    args = _parse_args()
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=level)
    asyncio.run(_main_async(args))
