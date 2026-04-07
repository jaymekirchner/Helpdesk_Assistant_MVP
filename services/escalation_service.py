"""Escalation detection — keyword + LLM-based uncertainty check."""

import json
import logging

from config.settings import openai_client, OPENAI_DEPLOYMENT
from config.constants import ESCALATION_TRIGGERS, ESCALATION_SUFFIX

logger = logging.getLogger(__name__)


class EscalationService:
    """Determines if an assistant response requires escalation to human IT support."""

    def __init__(self):
        self._openai = openai_client

    def check_escalation(self, answer: str) -> str:
        answer_lower = answer.lower()

        keyword_hit = any(trigger in answer_lower for trigger in ESCALATION_TRIGGERS)
        if keyword_hit:
            logger.debug("Escalation triggered by keyword match")
            return answer + ESCALATION_SUFFIX

        system_message = (
            "You are an escalation detector for an IT support assistant.\n\n"
            "Read the assistant's answer below and decide if it expresses "
            "any uncertainty, partial knowledge, or lack of confidence.\n\n"
            "The answer may be written in any language (English, French, Spanish, German, Arabic, "
            "Brazilian Portuguese, or others). Detect uncertainty signals regardless of language.\n\n"
            "Signals of uncertainty include:\n"
            "- Hedging language (may, might, could, possibly, perhaps — and their equivalents in other languages)\n"
            "- Partial answers or gaps ('this might help but...')\n"
            "- Suggestions to try something without confidence it will work\n"
            "- Any implication the answer is incomplete\n\n"
            "Respond ONLY with JSON:\n"
            '{"uncertain": true}  or  {"uncertain": false}\n\n'
            "No explanation. No markdown. JSON only."
        )

        try:
            response = self._openai.chat.completions.create(
                model=OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": answer},
                ],
                temperature=0,
                max_tokens=20,
            )
            raw = response.choices[0].message.content.strip()
            parsed = json.loads(raw)

            if parsed.get("uncertain", False):
                logger.debug("Escalation triggered by LLM confidence check")
                return answer + ESCALATION_SUFFIX
        except Exception as e:
            logger.debug("Escalation LLM check failed: %s — skipping", e)

        return answer

    @staticmethod
    def should_run_escalation_check(response_text: str) -> bool:
        return "i do not know based on the knowledge base" in response_text.lower()
