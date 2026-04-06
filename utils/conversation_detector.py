"""Conversation-state detection helpers — signal matching, extraction, and history inspection."""

import re

from config.constants import (
    FOLLOWUP_FAILURE_SIGNALS,
    ESCALATION_SUFFIX,
    TOOL_REQUEST_SIGNALS,
    TICKET_LOOKUP_SIGNALS,
    TICKET_REQUEST_SIGNALS,
    TICKET_CONFIRMATION_SIGNALS,
    LOOKUP_USERNAME_INPUT_PROMPT,
    LOOKUP_FIRST_NAME_PROMPT,
    LOOKUP_LAST_NAME_PROMPT,
    LOOKUP_DISAMBIGUATE_PROMPT,
    LOOKUP_NEXT_ACTION_PROMPT,
    KB_TICKET_IDENTITY_METHOD_PROMPT,
    KB_TICKET_USERNAME_INPUT_PROMPT,
    KB_TICKET_EMAIL_INPUT_PROMPT,
    KB_TICKET_FIRST_NAME_PROMPT,
    KB_TICKET_LAST_NAME_PROMPT,
    CC_EMAIL_PROMPT,
    CC_EMAIL_INPUT_PROMPT,
    TICKET_LOOKUP_NUMBER_PROMPT,
    TICKET_LOOKUP_METHOD_PROMPT,
    TICKET_LOOKUP_USER_PROMPT,
    TICKET_LOOKUP_USER_LAST_NAME_PROMPT,
    TICKET_LOOKUP_USERNAME_PROMPT,
    INPUT_SUMMARY_CONFIRM_MARKER,
)


class ConversationDetector:
    """Stateless helper that inspects user input and conversation history
    to determine the current conversation state / intent."""

    # ── Signal matchers ──────────────────────────────────────────────────────

    @staticmethod
    def looks_like_tool_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(signal in msg for signal in TOOL_REQUEST_SIGNALS)

    @staticmethod
    def looks_like_ticket_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(signal in msg for signal in TICKET_REQUEST_SIGNALS)

    @staticmethod
    def looks_like_ticket_confirmation(user_input: str) -> bool:
        msg = user_input.strip().lower()
        return any(msg == signal or msg.startswith(signal) for signal in TICKET_CONFIRMATION_SIGNALS)

    @staticmethod
    def looks_like_ticket_lookup_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in TICKET_LOOKUP_SIGNALS)

    @staticmethod
    def looks_like_direct_lookup_request(user_input: str) -> bool:
        msg = user_input.lower()
        return any(s in msg for s in ["lookup user", "look up user", "find a user", "user lookup"])

    # ── History inspectors ───────────────────────────────────────────────────

    @staticmethod
    def last_assistant_offered_escalation(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") == "assistant":
                return ESCALATION_SUFFIX in message.get("content", "")
        return False

    @staticmethod
    def last_assistant_requested_name_fields(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "first name" in content and "last name" in content
        return False

    @staticmethod
    def last_assistant_requested_identity_for_lookup(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "username or your email" in content or "username or email" in content
        return False

    @staticmethod
    def last_assistant_asked_lookup_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return "reply with 'username' or 'name'" in content
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_username(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return LOOKUP_USERNAME_INPUT_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_first_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return LOOKUP_FIRST_NAME_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_last_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return LOOKUP_LAST_NAME_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_disambiguating_device_id(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return LOOKUP_DISAMBIGUATE_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_lookup_next_action(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return LOOKUP_NEXT_ACTION_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_identity_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return KB_TICKET_IDENTITY_METHOD_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_username(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return KB_TICKET_USERNAME_INPUT_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_email(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return KB_TICKET_EMAIL_INPUT_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_first_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return KB_TICKET_FIRST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_kb_ticket_last_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return KB_TICKET_LAST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def get_kb_ticket_first_name_from_history(conversation_history: list) -> str:
        for i, msg in enumerate(conversation_history):
            if (
                msg.get("role") == "assistant"
                and KB_TICKET_FIRST_NAME_PROMPT.lower() in (msg.get("content") or "").lower()
                and i + 1 < len(conversation_history)
                and conversation_history[i + 1].get("role") == "user"
            ):
                return conversation_history[i + 1].get("content", "").strip()
        return ""

    @staticmethod
    def last_assistant_asked_for_ticket_number(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return TICKET_LOOKUP_NUMBER_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_cc_email(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return CC_EMAIL_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_cc_email_input(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return CC_EMAIL_INPUT_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_method(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return TICKET_LOOKUP_METHOD_PROMPT.lower() in content
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_user(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = (message.get("content") or "").lower()
            return (
                TICKET_LOOKUP_USER_PROMPT.lower() in content
                or TICKET_LOOKUP_USERNAME_PROMPT.lower() in content
            )
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_username(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return TICKET_LOOKUP_USERNAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_first_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return TICKET_LOOKUP_USER_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_ticket_lookup_last_name(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return TICKET_LOOKUP_USER_LAST_NAME_PROMPT.lower() in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_warned_about_duplicate_ticket(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return "ticket was already opened in this conversation" in (message.get("content") or "").lower()
        return False

    @staticmethod
    def last_assistant_asked_for_input_confirmation(conversation_history: list) -> bool:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            return INPUT_SUMMARY_CONFIRM_MARKER in (message.get("content") or "")
        return False

    # ── Extractors ───────────────────────────────────────────────────────────

    @staticmethod
    def extract_first_last_name(user_input: str):
        explicit = re.search(
            r"first\s+name\s*(?:is|:)?\s*([A-Za-z'\-]+).*last\s+name\s*(?:is|:)?\s*([A-Za-z'\-]+)",
            user_input,
            flags=re.IGNORECASE,
        )
        if explicit:
            return explicit.group(1), explicit.group(2)
        cleaned = re.sub(r"[^A-Za-z'\-\s]", " ", user_input).strip()
        tokens = [t for t in cleaned.split() if t]
        if len(tokens) >= 2:
            return tokens[0], tokens[-1]
        return None, None

    @staticmethod
    def extract_identity_value(user_input: str):
        email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", user_input)
        if email_match:
            return email_match.group(0), "email"
        username_match = re.search(r"\b[a-zA-Z][a-zA-Z0-9._-]{2,}\b", user_input)
        if username_match:
            return username_match.group(0), "username"
        return None, None

    @staticmethod
    def normalize_lookup_username(identity_value: str, identity_kind: str) -> str:
        if identity_kind == "email":
            return identity_value.split("@", 1)[0].strip().lower()
        return identity_value.strip().lower()

    @staticmethod
    def extract_ticket_id_from_input(user_input: str) -> str:
        match = re.search(r"\b(\d{4,})\b", user_input)
        return match.group(1) if match else ""

    @staticmethod
    def extract_ticket_lookup_target(user_input: str):
        username_match = re.search(
            r"\b(?:for|by)\s+([a-zA-Z][a-zA-Z0-9._-]{2,}(?:\.[a-zA-Z][a-zA-Z0-9._-]{1,})+)\b",
            user_input,
            re.IGNORECASE,
        )
        if username_match:
            return username_match.group(1), "username"
        name_match = re.search(
            r"\b(?:for|by)\s+([A-Za-z][a-z]+)\s+([A-Za-z][a-z]+)\b",
            user_input,
        )
        if name_match:
            return (name_match.group(1), name_match.group(2)), "name"
        return None, None

    @staticmethod
    def extract_lookup_by_keyword(user_input: str) -> str:
        msg = user_input.lower()
        if "by" not in msg:
            return ""
        if re.search(r"\bby\s+username\b", msg):
            return "username"
        if re.search(r"\bby\s+(user|name|first\s+name|last\s+name)\b", msg):
            return "name"
        if re.search(r"\bby\s+(number|ticket\s*number|ticket|id|ticket\s*id)\b", msg):
            return "number"
        return ""

    # ── History data extractors ──────────────────────────────────────────────

    @staticmethod
    def get_first_name_from_lookup_history(conversation_history: list) -> str:
        for i, msg in enumerate(conversation_history):
            if (
                msg.get("role") == "assistant"
                and LOOKUP_FIRST_NAME_PROMPT.lower() in (msg.get("content") or "").lower()
                and i + 1 < len(conversation_history)
                and conversation_history[i + 1].get("role") == "user"
            ):
                return conversation_history[i + 1].get("content", "").strip()
        return ""

    @staticmethod
    def get_ticket_lookup_first_name_from_history(conversation_history: list) -> str:
        for i, msg in enumerate(conversation_history):
            if (
                msg.get("role") == "assistant"
                and TICKET_LOOKUP_USER_PROMPT.lower() in (msg.get("content") or "").lower()
                and i + 1 < len(conversation_history)
                and conversation_history[i + 1].get("role") == "user"
            ):
                return conversation_history[i + 1].get("content", "").strip()
        return ""

    @staticmethod
    def get_username_from_lookup_result(conversation_history: list) -> str:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "user found:" in content.lower() or "match 1:" in content.lower():
                match = re.search(r"-\s*Username:\s*(\S+)", content, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
        return ""

    @staticmethod
    def get_user_by_match_number(conversation_history: list, match_num: int) -> str:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "users found with that name:" not in content.lower():
                continue
            pattern = rf"Match {match_num}:\n((?:- [^\n]+\n?)+)"
            m = re.search(pattern, content, re.IGNORECASE)
            if m:
                return m.group(0).strip()
        return ""

    @staticmethod
    def ticket_already_created_in_session(conversation_history: list) -> str:
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content") or ""
            if "ticket created successfully" in content.lower():
                match = re.search(r"ID:\s*(\S+)", content, re.IGNORECASE)
                return match.group(1).rstrip(".,;)") if match else "unknown"
        return ""

    @staticmethod
    def user_reports_failed_steps(user_input: str, conversation_history: list) -> bool:
        msg = user_input.lower()
        mentions_failure = any(signal in msg for signal in FOLLOWUP_FAILURE_SIGNALS)
        if not mentions_failure:
            return False
        for message in reversed(conversation_history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content", "")
            had_steps = "1." in content and "2." in content
            had_escalation = ESCALATION_SUFFIX in content
            return had_steps and not had_escalation
        return False
