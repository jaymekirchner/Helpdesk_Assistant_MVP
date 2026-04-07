"""Custom evaluator: Escalation Accuracy.

Measures whether the EscalationService correctly appended (or withheld)
the escalation warning for a given agent response.

Two sub-metrics are reported:
  escalation_accuracy         — 1.0 if the escalation decision matches
                                 the expected label, 0.0 otherwise.
  false_escalation_rate       — 1.0 if the agent escalated when it should
                                 NOT have (false positive).  0.0 otherwise.
  missed_escalation_rate      — 1.0 if the agent did NOT escalate when it
                                 SHOULD have (false negative).  0.0 otherwise.

Expected dataset columns
------------------------
query               : str   — the original user question (context only)
response            : str   — the final agent response (after EscalationService)
expected_escalation : bool  — ground-truth: should this response be escalated?

Output columns
--------------
escalation_accuracy        : float  — 1.0 correct decision, 0.0 wrong decision
false_escalation_rate      : float  — 1.0 if false positive, else 0.0
missed_escalation_rate     : float  — 1.0 if false negative, else 0.0
escalation_accuracy_reason : str    — human-readable explanation
"""

from __future__ import annotations

import logging
import sys
import os
from typing import Any

# Allow imports from the project root when running standalone.
_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from config.constants import ESCALATION_SUFFIX
except ImportError:
    # Fallback if constants are not importable (e.g., in isolated CI).
    ESCALATION_SUFFIX = "\n\n⚠️ If not, please contact IT support if the issue persists."

logger = logging.getLogger(__name__)

# Normalised string to detect escalation in a response.
_ESCALATION_MARKER = ESCALATION_SUFFIX.strip()


def _normalise_bool(value: Any) -> bool:
    """Accept bool, int, or string representations of a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


class EscalationAccuracyEvaluator:
    """Deterministic evaluator for the EscalationService escalation decision.

    Compatible with ``azure.ai.evaluation.evaluate()`` custom evaluator protocol.
    """

    # Stable identifier used by Azure AI Foundry to track this evaluator across runs.
    id = "escalation_accuracy"

    def __call__(
        self,
        *,
        query: str,
        response: str,
        expected_escalation: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Score a single escalation decision.

        Parameters
        ----------
        query:
            The original user message (used for logging/context only).
        response:
            The full agent response text (may or may not contain
            ESCALATION_SUFFIX depending on what EscalationService decided).
        expected_escalation:
            Ground-truth flag: ``True`` if the response *should* have been
            escalated, ``False`` if it should not.

        Returns
        -------
        dict containing:
            ``escalation_accuracy``        float  1.0 / 0.0
            ``false_escalation_rate``      float  1.0 / 0.0
            ``missed_escalation_rate``     float  1.0 / 0.0
            ``escalation_accuracy_reason`` str
        """
        expected = _normalise_bool(expected_escalation)
        actual = _ESCALATION_MARKER in (response or "")

        correct = actual == expected

        # Sub-metric flags
        false_positive = actual and not expected   # escalated when it should not have
        false_negative = not actual and expected   # did NOT escalate when it should have

        score = 1.0 if correct else 0.0
        fp_score = 1.0 if false_positive else 0.0
        fn_score = 1.0 if false_negative else 0.0

        # Build a readable reason string.
        expected_label = "ESCALATE" if expected else "NO_ESCALATE"
        actual_label = "ESCALATED" if actual else "NOT_ESCALATED"

        if correct:
            reason = (
                f"PASS — expected {expected_label}, agent {actual_label}. "
                f"Decision is correct."
            )
        elif false_positive:
            reason = (
                f"FAIL (false positive) — expected {expected_label} but agent "
                f"{actual_label}. The escalation warning was added unnecessarily, "
                f"which may reduce user confidence for well-resolved issues."
            )
        else:  # false_negative
            reason = (
                f"FAIL (missed escalation) — expected {expected_label} but agent "
                f"{actual_label}. The agent did not surface the escalation warning "
                f"for an uncertain response, leaving the user without guidance to "
                f"seek human IT support."
            )

        logger.debug(
            "escalation_accuracy | expected=%s actual=%s score=%.1f query=%r",
            expected_label,
            actual_label,
            score,
            query[:80],
        )

        return {
            "escalation_accuracy": score,
            "false_escalation_rate": fp_score,
            "missed_escalation_rate": fn_score,
            "escalation_accuracy_reason": reason,
        }
