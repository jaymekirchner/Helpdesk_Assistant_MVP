"""IT Helpdesk Agent — Evaluation Orchestration Script.

Runs both custom evaluation metrics and (optionally) uploads results to
an Azure AI Foundry project for tracking and trending.

Metrics evaluated
-----------------
1. Tool Selection Accuracy
   - Does the ActionAgent select the correct MCP tool for each query?
   - Measures precision of the LLM's tool-routing decision under the
     ActionAgent system prompt.

2. Escalation Accuracy
   - Does the EscalationService correctly append (or withhold) the
     escalation warning for uncertain vs. confident responses?
   - Sub-metrics: false_escalation_rate, missed_escalation_rate.

Workflow
--------
Step 1  Run runner.py to generate result JSONL files.
Step 2  Feed those JSONL files through azure.ai.evaluation.evaluate()
        together with the custom evaluators.
Step 3  Print a human-readable summary to stdout.
Step 4  (Optional) Upload results to Azure AI Foundry for tracking.

Usage
-----
Basic (local only):
    python -m evaluation.run_eval

With Foundry upload:
    python -m evaluation.run_eval \\
        --foundry-endpoint https://<account>.services.ai.azure.com/api/projects/<project> \\
        --deployment gpt-4o

Skip runner (re-use existing result files):
    python -m evaluation.run_eval --skip-runner

Environment variables (override CLI flags):
    AZURE_AI_PROJECT_ENDPOINT   — Foundry project endpoint
    AZURE_OPENAI_DEPLOYMENT     — model deployment name used for tracing
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# ── Path setup ───────────────────────────────────────────────────────────────
_ROOT = str(Path(__file__).parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
RESULTS_DIR = _HERE / "results"
TOOL_SELECTION_RESULTS = RESULTS_DIR / "tool_selection_results.jsonl"
ESCALATION_RESULTS = RESULTS_DIR / "escalation_results.jsonl"

# ── Evaluator registry ────────────────────────────────────────────────────────
from evaluation.evaluators.tool_selection_accuracy import ToolSelectionAccuracyEvaluator
from evaluation.evaluators.escalation_accuracy import EscalationAccuracyEvaluator


# ── Helpers ────────────────────────────────────────────────────────────────────


def _load_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _print_banner(title: str) -> None:
    print("\n" + "═" * 72)
    print(f"  {title}")
    print("═" * 72)


def _extract_row_field(
    row: dict[str, Any],
    key: str,
    evaluator_name: str,
) -> Any:
    """Extract a field from an azure.ai.evaluation flat-key row dict.

    The SDK flattens nested output as:
        "outputs.<evaluator_name>.<field>"  (custom evaluator)
    but also falls back to a direct key for locally-scored rows.
    """
    # Flat SDK format: "outputs.tool_selection.tool_selection_accuracy"
    sdk_key = f"outputs.{evaluator_name}.{key}"
    if sdk_key in row:
        return row[sdk_key]
    # Direct key (local fallback rows)
    return row.get(key)


def _query_from_row(row: dict[str, Any]) -> str:
    """Return the query string regardless of key format."""
    return (
        row.get("inputs.query")
        or row.get("query")
        or ""
    )


def _print_metric_table(
    title: str,
    rows: list[dict[str, Any]],
    metric_keys: list[str],
    reason_key: str | None = None,
    evaluator_name: str = "",
) -> None:
    """Print a tabular summary of evaluation results."""
    if not rows:
        print(f"  [!] No data for {title}")
        return

    print(f"\n── {title} ──")

    q_width = 60

    for row in rows:
        query_str = _query_from_row(row)[:q_width]
        parts = []
        for k in metric_keys:
            val = _extract_row_field(row, k, evaluator_name) if evaluator_name else row.get(k)
            parts.append(f"{k}={val if val is not None else 'N/A'}")
        score_parts = ", ".join(parts)
        reason_str = ""
        if reason_key:
            reason_val = (
                _extract_row_field(row, reason_key, evaluator_name)
                if evaluator_name
                else row.get(reason_key)
            )
            if reason_val:
                reason_str = f"\n    ↳ {reason_val}"
        print(f"  {query_str:<{q_width}}  |  {score_parts}{reason_str}")

    # Per-column averages (skip None)
    averages = {}
    for k in metric_keys:
        values = [
            float(v)
            for row in rows
            for v in [_extract_row_field(row, k, evaluator_name) if evaluator_name else row.get(k)]
            if v is not None
        ]
        averages[k] = (sum(values) / len(values)) if values else 0.0

    avg_line = "  ".join(f"{k}={v:.3f}" for k, v in averages.items())
    print(f"\n  AVERAGE: {avg_line}")


def _compute_averages(rows: list[dict], metric_keys: list[str]) -> dict[str, float]:
    result = {}
    for k in metric_keys:
        values = [float(r[k]) for r in rows if k in r]
        result[k] = (sum(values) / len(values)) if values else 0.0
    return result


# ── Core evaluation logic ──────────────────────────────────────────────────────


def _run_tool_selection_eval(
    results_path: Path,
    azure_ai_project: dict | None = None,
) -> dict[str, float]:
    """Run azure.ai.evaluation on the tool-selection result JSONL.

    Returns a dict of metric averages.
    """
    try:
        from azure.ai.evaluation import evaluate  # type: ignore[import]
    except ImportError:
        logger.warning(
            "azure-ai-evaluation is not installed — falling back to local scoring."
        )
        return _local_score_tool_selection(results_path)

    evaluator = ToolSelectionAccuracyEvaluator()

    eval_kwargs: dict[str, Any] = dict(
        data=str(results_path),
        evaluators={"tool_selection": evaluator},
        evaluator_config={
            "tool_selection": {
                "column_mapping": {
                    "query": "${data.query}",
                    "expected_tool": "${data.expected_tool}",
                    "tool_calls": "${data.tool_calls}",
                }
            }
        },
    )

    if azure_ai_project:
        eval_kwargs["azure_ai_project"] = azure_ai_project

    output = evaluate(**eval_kwargs)

    metrics = output.get("metrics", {})
    rows = output.get("rows", [])

    # Print per-row table using the flat SDK key format.
    _print_metric_table(
        "Tool Selection Accuracy (per row)",
        rows,
        ["tool_selection_accuracy"],
        "tool_selection_accuracy_reason",
        evaluator_name="tool_selection",
    )

    # If the SDK aggregate is empty (custom evaluator aggregation warning),
    # compute averages ourselves from the row-level outputs.
    result_metrics = {k: v for k, v in metrics.items() if "tool_selection" in k.lower()}
    if not result_metrics and rows:
        values = [
            float(v)
            for row in rows
            for v in [row.get("outputs.tool_selection.tool_selection_accuracy")]
            if v is not None
        ]
        result_metrics["tool_selection_accuracy"] = (
            sum(values) / len(values) if values else 0.0
        )
    return result_metrics


def _run_escalation_eval(
    results_path: Path,
    azure_ai_project: dict | None = None,
) -> dict[str, float]:
    """Run azure.ai.evaluation on the escalation result JSONL.

    Returns a dict of metric averages.
    """
    try:
        from azure.ai.evaluation import evaluate  # type: ignore[import]
    except ImportError:
        logger.warning(
            "azure-ai-evaluation is not installed — falling back to local scoring."
        )
        return _local_score_escalation(results_path)

    evaluator = EscalationAccuracyEvaluator()

    eval_kwargs: dict[str, Any] = dict(
        data=str(results_path),
        evaluators={"escalation": evaluator},
        evaluator_config={
            "escalation": {
                "column_mapping": {
                    "query": "${data.query}",
                    "response": "${data.response}",
                    "expected_escalation": "${data.expected_escalation}",
                }
            }
        },
    )

    if azure_ai_project:
        eval_kwargs["azure_ai_project"] = azure_ai_project

    output = evaluate(**eval_kwargs)

    metrics = output.get("metrics", {})
    rows = output.get("rows", [])

    _print_metric_table(
        "Escalation Accuracy (per row)",
        rows,
        ["escalation_accuracy", "false_escalation_rate", "missed_escalation_rate"],
        "escalation_accuracy_reason",
        evaluator_name="escalation",
    )

    result_metrics = {
        k: v
        for k, v in metrics.items()
        if "escalation" in k.lower() or "false_" in k.lower() or "missed_" in k.lower()
    }
    if not result_metrics and rows:
        for metric_col in ["escalation_accuracy", "false_escalation_rate", "missed_escalation_rate"]:
            sdk_col = f"outputs.escalation.{metric_col}"
            values = [
                float(v)
                for row in rows
                for v in [row.get(sdk_col)]
                if v is not None
            ]
            result_metrics[metric_col] = sum(values) / len(values) if values else 0.0
    return result_metrics


# ── Local fallback scorers (no azure-ai-evaluation SDK required) ──────────────


def _local_score_tool_selection(results_path: Path) -> dict[str, float]:
    """Score tool selection without the azure-ai-evaluation package."""
    rows = _load_jsonl(results_path)
    if not rows:
        return {}

    evaluator = ToolSelectionAccuracyEvaluator()
    scored: list[dict] = []
    for row in rows:
        result = evaluator(
            query=row.get("query", ""),
            expected_tool=row.get("expected_tool", ""),
            tool_calls=row.get("tool_calls", "[]"),
        )
        scored.append({**row, **result})

    avgs = _compute_averages(scored, ["tool_selection_accuracy"])
    _print_metric_table(
        "Tool Selection Accuracy (local, per row)",
        scored,
        ["tool_selection_accuracy"],
        "tool_selection_accuracy_reason",
    )
    return avgs


def _local_score_escalation(results_path: Path) -> dict[str, float]:
    """Score escalation without the azure-ai-evaluation package."""
    rows = _load_jsonl(results_path)
    if not rows:
        return {}

    evaluator = EscalationAccuracyEvaluator()
    scored: list[dict] = []
    for row in rows:
        result = evaluator(
            query=row.get("query", ""),
            response=row.get("response", ""),
            expected_escalation=row.get("expected_escalation", False),
        )
        scored.append({**row, **result})

    avgs = _compute_averages(
        scored,
        ["escalation_accuracy", "false_escalation_rate", "missed_escalation_rate"],
    )
    _print_metric_table(
        "Escalation Accuracy (local, per row)",
        scored,
        ["escalation_accuracy", "false_escalation_rate", "missed_escalation_rate"],
        "escalation_accuracy_reason",
    )
    return avgs


# ── Final summary ─────────────────────────────────────────────────────────────


def _print_summary(metric_dict: dict[str, float]) -> None:
    _print_banner("IT Helpdesk Agent — Evaluation Summary")
    if not metric_dict:
        print("  No metrics computed.")
        return

    # Group metrics by category
    sections: dict[str, list[tuple[str, float]]] = {
        "Tool Selection": [],
        "Escalation": [],
    }

    for k, v in sorted(metric_dict.items()):
        if "tool_selection" in k:
            sections["Tool Selection"].append((k, v))
        else:
            sections["Escalation"].append((k, v))

    # Metrics where LOWER is better (error rates)
    _ERROR_RATE_SUFFIX = ("false_escalation_rate", "missed_escalation_rate")

    for section, items in sections.items():
        if not items:
            continue
        print(f"\n  ▸ {section}")
        for k, v in items:
            is_err = any(k.endswith(s) for s in _ERROR_RATE_SUFFIX)
            bar_len = int(v * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            pct = f"{v * 100:5.1f}%"
            label = " (lower is better)" if is_err else ""
            print(f"    {k:<45} {pct}  [{bar}]{label}")

    print()


# ── CLI ────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="run_eval.py — IT Helpdesk Agent Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--skip-runner",
        action="store_true",
        help="Skip runner.py and use existing result files.",
    )
    p.add_argument(
        "--tool-only",
        action="store_true",
        help="Evaluate tool selection metric only.",
    )
    p.add_argument(
        "--escalation-only",
        action="store_true",
        help="Evaluate escalation metric only.",
    )
    p.add_argument(
        "--foundry-endpoint",
        default=os.getenv("AZURE_AI_PROJECT_ENDPOINT", ""),
        help=(
            "Azure AI Foundry project endpoint for cloud tracking. "
            "Format: https://<account>.services.ai.azure.com/api/projects/<project>"
        ),
    )
    p.add_argument(
        "--deployment",
        default=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
        help="Azure OpenAI deployment name (used when azure_ai_project is set).",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Enable DEBUG logging.")
    return p.parse_args()


async def main() -> None:
    args = _parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        format="%(levelname)s %(name)s: %(message)s",
        level=level,
    )

    run_tool = not args.escalation_only
    run_esc = not args.tool_only

    # ── Step 1: Runner ──────────────────────────────────────────────────────
    if not args.skip_runner:
        from evaluation.runner import (  # noqa: PLC0415
            run_escalation_runner,
            run_tool_selection_runner,
        )

        _print_banner("Step 1 — Generating Agent Responses")

        if run_esc:
            run_escalation_runner()
        if run_tool:
            await run_tool_selection_runner()
    else:
        print("[run_eval] --skip-runner set — using existing result files.")

    # ── Step 2: Build azure_ai_project config ───────────────────────────────
    azure_ai_project: dict | None = None
    if args.foundry_endpoint:
        azure_ai_project = {
            "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID", ""),
            "resource_group_name": os.getenv("AZURE_RESOURCE_GROUP", ""),
            "project_name": args.foundry_endpoint.rstrip("/").split("/")[-1],
            "endpoint": args.foundry_endpoint,
        }
        if args.deployment:
            azure_ai_project["aoai_deployment"] = args.deployment
        print(f"\n[run_eval] Foundry tracking enabled → {args.foundry_endpoint}")
    else:
        print(
            "\n[run_eval] No Foundry endpoint set — running local evaluation only.\n"
            "           Pass --foundry-endpoint (or AZURE_AI_PROJECT_ENDPOINT) to "
            "upload results to Azure AI Foundry."
        )

    # ── Step 3: Evaluate ────────────────────────────────────────────────────
    _print_banner("Step 2 — Running Evaluations")

    all_metrics: dict[str, float] = {}

    if run_tool and TOOL_SELECTION_RESULTS.exists():
        print("\n[run_eval] ⚙  Evaluating Tool Selection Accuracy...")
        tool_metrics = _run_tool_selection_eval(TOOL_SELECTION_RESULTS, azure_ai_project)
        all_metrics.update(tool_metrics)
    elif run_tool:
        print(
            f"[run_eval] Warning: Tool selection results file not found at "
            f"{TOOL_SELECTION_RESULTS}. Run without --skip-runner first."
        )

    if run_esc and ESCALATION_RESULTS.exists():
        print("\n[run_eval] ⚙  Evaluating Escalation Accuracy...")
        esc_metrics = _run_escalation_eval(ESCALATION_RESULTS, azure_ai_project)
        all_metrics.update(esc_metrics)
    elif run_esc:
        print(
            f"[run_eval] Warning: Escalation results file not found at "
            f"{ESCALATION_RESULTS}. Run without --skip-runner first."
        )

    # ── Step 4: Summary ─────────────────────────────────────────────────────
    _print_summary(all_metrics)

    # Error-rate metrics: fail if value EXCEEDS the threshold (inverted logic).
    _ERROR_RATE_KEYS = frozenset({"false_escalation_rate", "missed_escalation_rate"})
    threshold = float(os.getenv("EVAL_PASS_THRESHOLD", "0.70"))
    error_rate_threshold = float(os.getenv("EVAL_ERROR_RATE_THRESHOLD", "0.25"))

    failures = []
    for k, v in all_metrics.items():
        if "reason" in k:
            continue
        is_err = any(m in k for m in _ERROR_RATE_KEYS)
        if is_err:
            if v > error_rate_threshold:
                failures.append((k, v, f"exceeds error-rate threshold ({error_rate_threshold:.0%})"))
        else:
            if v < threshold:
                failures.append((k, v, f"below threshold ({threshold:.0%})"))

    if failures:
        print(
            f"  ⚠  {len(failures)} metric(s) outside acceptable range:\n"
            + "\n".join(f"    • {k}: {v:.3f} — {reason}" for k, v, reason in failures)
        )
        sys.exit(1)

    print("  ✓ All metrics within acceptable range.\n")


if __name__ == "__main__":
    asyncio.run(main())
