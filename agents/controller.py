"""Agent Controller — top-level message handler with conversation-state machine."""

import re
import json

from config.settings import openai_client, OPENAI_DEPLOYMENT
from config.constants import (
    HISTORY_LIMIT,
    ESCALATION_SUFFIX,
    LONG_INPUT_THRESHOLD,
    INPUT_SUMMARY_CONFIRM_MARKER,
    IDENTITY_LOOKUP_PROMPT,
    LOOKUP_METHOD_PROMPT,
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
)
from prompts.orchestrator import TICKET_CONTEXT_EXTRACTOR_SYSTEM, INPUT_SUMMARIZER_SYSTEM
from services.escalation_service import EscalationService
from agents.agent_factory import action_agent
from agents.orchestrator import run_orchestrator
from utils.conversation_detector import ConversationDetector

escalation = EscalationService()
detector = ConversationDetector()


# ── Helper functions ─────────────────────────────────────────────────────────

def build_ticket_prompt(ctx: dict) -> str:
    prompt = (
        f"Create an IT support ticket with the following details:\n"
        f"- user: {ctx['user']}\n"
        f"- issue: {ctx['issue']}\n"
        f"- category: {ctx['category']}\n"
        f"- severity: {ctx['severity']}\n"
        f"- impacted_system: {ctx['impacted_system']}\n"
    )
    if ctx.get("first_name"):
        prompt += f"- first_name: {ctx['first_name']}\n"
    if ctx.get("last_name"):
        prompt += f"- last_name: {ctx['last_name']}\n"
    if ctx.get("additional_cc_emails"):
        prompt += f"- additional_cc_emails: {ctx['additional_cc_emails']}\n"
    prompt += "Call create_ticket now with these exact values."
    return prompt


def summarize_long_input(user_input: str) -> str:
    if not openai_client:
        return user_input[:LONG_INPUT_THRESHOLD]
    try:
        resp = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": INPUT_SUMMARIZER_SYSTEM},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        print(f"[summarize_long_input] LLM call failed: {exc} — truncating instead")
        return user_input[:LONG_INPUT_THRESHOLD]


def extract_summary_from_confirmation_message(conversation_history: list) -> str:
    for message in reversed(conversation_history):
        if message.get("role") != "assistant":
            continue
        content = message.get("content") or ""
        if INPUT_SUMMARY_CONFIRM_MARKER not in content:
            break
        match = re.search(
            r"Here is my summary:\n\n(.+?)(?:\n\n|$)",
            content,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        break
    return ""


def extract_ticket_context(conversation_history: list) -> dict:
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in conversation_history[-HISTORY_LIMIT:]
    )

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": TICKET_CONTEXT_EXTRACTOR_SYSTEM},
                {"role": "user", "content": history_text},
            ],
            temperature=0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        print(f"[DEBUG] Extracted ticket context: {raw}")
        parsed = json.loads(raw)
        return {
            "issue": parsed.get("issue", "Unresolved IT issue"),
            "category": parsed.get("category", "General"),
            "severity": parsed.get("severity", "Medium"),
            "impacted_system": parsed.get("impacted_system", "Unknown"),
            "user": parsed.get("user", "unknown"),
            "first_name": parsed.get("first_name", ""),
            "last_name": parsed.get("last_name", ""),
            "device_id": parsed.get("device_id", ""),
        }
    except Exception as e:
        print(f"[DEBUG] Ticket context extraction failed: {e} — using defaults")
        return {
            "issue": "Unresolved IT issue from conversation",
            "category": "General",
            "severity": "Medium",
            "impacted_system": "Unknown",
            "user": "unknown",
            "first_name": "",
            "last_name": "",
            "device_id": "",
        }


# ── Main handler ─────────────────────────────────────────────────────────────

async def handle_user_message(user_input: str, conversation_history: list):
    print("\n[Agent Controller] Evaluating message...")

    # Pre-check: repeated input
    if conversation_history:
        last_user_msg = next(
            (m.get("content", "") for m in reversed(conversation_history) if m.get("role") == "user"),
            None,
        )
        if last_user_msg and last_user_msg.strip().lower() == user_input.strip().lower():
            print("[Agent Controller] Repeated input detected — sending clarification prompt.")
            return (
                "It looks like you sent the same message again. "
                "Are you still waiting for something, or would you like to rephrase your request?"
            ), True

    # Pre-check: long-input confirmation
    if conversation_history and detector.last_assistant_asked_for_input_confirmation(conversation_history):
        confirmed = user_input.strip().lower() in (
            "yes", "yes please", "yep", "yeah", "correct", "looks good",
            "that's right", "that is right", "ok", "okay", "sure",
        )
        if confirmed:
            effective_input = extract_summary_from_confirmation_message(conversation_history)
            if not effective_input:
                effective_input = user_input
        else:
            effective_input = user_input.strip()
        print(f"[Agent Controller] Long-input confirmation received — routing with: {effective_input[:80]}...")
        response = await run_orchestrator(effective_input, conversation_history)
        if escalation.should_run_escalation_check(response):
            final_response = escalation.check_escalation(response)
        else:
            final_response = response
        return final_response, True

    # Pre-check: long input — summarize and ask the user to verify
    if len(user_input) > LONG_INPUT_THRESHOLD and openai_client:
        print(f"[Agent Controller] Long input ({len(user_input)} chars) — summarizing before routing.")
        summary = summarize_long_input(user_input)
        return (
            f"Here is my summary:\n\n{summary}\n\n"
            f"{INPUT_SUMMARY_CONFIRM_MARKER} "
            "Reply **Yes** to proceed, or correct any details."
        ), True

    # Pre-check: CC email address received — create the ticket with the extra CC
    if conversation_history and detector.last_assistant_asked_for_cc_email_input(conversation_history):
        email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", user_input)
        if not email_match:
            return "That doesn't look like a valid email address. Please try again.", True
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        ctx = extract_ticket_context(conversation_history)
        ctx["additional_cc_emails"] = [email_match.group(0)]
        tool_prompt = build_ticket_prompt(ctx)
        print(f"[DEBUG] Ticket prompt with additional CC: {tool_prompt}")
        action_response = await action_agent.run(tool_prompt)
        return action_response.text, True

    # Pre-check: CC email yes/no response
    if conversation_history and detector.last_assistant_asked_for_cc_email(conversation_history):
        choice = user_input.strip().lower()
        if choice in ("yes", "yes please", "yep", "yeah", "sure", "ok", "okay"):
            return CC_EMAIL_INPUT_PROMPT, True
        # "No" or anything else → proceed with ticket creation (no additional CC)
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        ctx = extract_ticket_context(conversation_history)
        tool_prompt = build_ticket_prompt(ctx)
        print(f"[DEBUG] Ticket prompt (no additional CC): {tool_prompt}")
        action_response = await action_agent.run(tool_prompt)
        return action_response.text, True

    # Pre-check: KB ticket flow — email value received → ask about CC
    if conversation_history and detector.last_assistant_asked_for_kb_ticket_email(conversation_history):
        email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", user_input)
        if not email_match:
            return "That doesn't look like a valid email address. Please try again.", True
        print(f"[DEBUG] KB escalation (email) — prompting for CC email")
        return CC_EMAIL_PROMPT, True

    # Pre-check: KB ticket flow — username value received → ask about CC
    if conversation_history and detector.last_assistant_asked_for_kb_ticket_username(conversation_history):
        username = user_input.strip()
        if not username:
            return KB_TICKET_USERNAME_INPUT_PROMPT, True
        print(f"[DEBUG] KB escalation (username) — prompting for CC email")
        return CC_EMAIL_PROMPT, True

    # Pre-check: KB ticket flow — last name received (name-based identity) → ask about CC
    if conversation_history and detector.last_assistant_asked_for_kb_ticket_last_name(conversation_history):
        last_name = user_input.strip()
        if not last_name:
            return KB_TICKET_LAST_NAME_PROMPT, True
        first_name = detector.get_kb_ticket_first_name_from_history(conversation_history)
        if not first_name:
            return "I couldn't retrieve the first name. Please start over.", True
        print(f"[DEBUG] KB escalation (name) — prompting for CC email")
        return CC_EMAIL_PROMPT, True

    # Pre-check: KB ticket flow — first name received, ask for last name
    if conversation_history and detector.last_assistant_asked_for_kb_ticket_first_name(conversation_history):
        print("[Agent Controller] KB ticket first name received — asking for last name")
        return KB_TICKET_LAST_NAME_PROMPT, True

    # Pre-check: KB ticket flow — method choice (username vs email vs name)
    if conversation_history and detector.last_assistant_asked_for_kb_ticket_identity_method(conversation_history):
        choice = user_input.strip().lower()
        if "username" in choice:
            return KB_TICKET_USERNAME_INPUT_PROMPT, True
        elif "email" in choice:
            return KB_TICKET_EMAIL_INPUT_PROMPT, True
        elif "name" in choice:
            return KB_TICKET_FIRST_NAME_PROMPT, True
        else:
            return KB_TICKET_IDENTITY_METHOD_PROMPT, True

    # Pre-check: ticket confirmation following escalation offer → ask about CC
    is_confirmation = (
        detector.looks_like_ticket_confirmation(user_input)
        and detector.last_assistant_offered_escalation(conversation_history)
    )
    if is_confirmation:
        print("[Agent Controller] Decision → TICKET CONFIRMATION → ActionAgent")
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        ctx = extract_ticket_context(conversation_history)
        if ctx["user"] == "unknown":
            print("[Agent Controller] User identity unknown — requesting identity method before ticket creation")
            return KB_TICKET_IDENTITY_METHOD_PROMPT, True
        print("[Agent Controller] Ticket confirmation — prompting for CC email")
        return CC_EMAIL_PROMPT, True

    # Identity for lookup
    if conversation_history and detector.last_assistant_requested_identity_for_lookup(conversation_history):
        identity_value, identity_kind = detector.extract_identity_value(user_input)
        if not identity_value:
            return (
                "I still need either your username or your email to continue account lookup. "
                "Please provide one of those."
            ), True
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        lookup_username = detector.normalize_lookup_username(identity_value, identity_kind)
        followup_prompt = (
            "The user provided account identity details.\n"
            f"Provided {identity_kind}: {identity_value}\n"
            f"Username for lookup_user: {lookup_username}\n\n"
            "Use lookup_user with that username now. "
            "Then continue the ticket workflow using conversation context and create the ticket when ready."
        )
        action_response = await action_agent.run(followup_prompt)
        return action_response.text, True

    # Name fields provided
    if conversation_history and detector.last_assistant_requested_name_fields(conversation_history):
        first_name, last_name = detector.extract_first_last_name(user_input)
        if first_name and last_name:
            print("[Agent Controller] Name fields detected in user reply — continuing action flow.")
            return IDENTITY_LOOKUP_PROMPT, True

    # Ticket field request from assistant
    if conversation_history:
        last_msg = conversation_history[-1]
        if last_msg.get("role") == "assistant" and "required fields to create the ticket" in last_msg.get("content", ""):
            parts = [p.strip() for p in user_input.split(",")]
            issue = parts[0] if len(parts) > 0 else "Unspecified issue"
            user = parts[1] if len(parts) > 1 else "unknown"
            severity = parts[2] if len(parts) > 2 else "Medium"
            category = parts[3] if len(parts) > 3 else "General"
            impacted_system = parts[4] if len(parts) > 4 else "Unknown"
            ticket_prompt = (
                f"Create an IT support ticket with the following details:\n"
                f"- user: {user}\n"
                f"- issue: {issue}\n"
                f"- category: {category}\n"
                f"- severity: {severity}\n"
                f"- impacted_system: {impacted_system}\n"
                "Call create_ticket now with these exact values."
            )
            print(f"[Agent Controller] Auto-creating ticket from user reply: {ticket_prompt}")
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True

    # ── Lookup method selection flow ─────────────────────────────────────────

    # Match number for disambiguating multiple name matches
    if conversation_history and detector.last_assistant_asked_for_disambiguating_device_id(conversation_history):
        num_match = re.search(r"\b(\d+)\b", user_input)
        if not num_match:
            return LOOKUP_DISAMBIGUATE_PROMPT, True
        match_num = int(num_match.group(1))
        user_block = detector.get_user_by_match_number(conversation_history, match_num)
        if not user_block:
            return LOOKUP_DISAMBIGUATE_PROMPT, True
        print(f"[Agent Controller] Decision → DISAMBIGUATE by match number: {match_num}")
        return f"User found:\n{user_block}\n\n{LOOKUP_NEXT_ACTION_PROMPT}", True

    # Next action after successful lookup
    if conversation_history and detector.last_assistant_asked_for_lookup_next_action(conversation_history):
        choice = user_input.strip().lower()
        username = detector.get_username_from_lookup_result(conversation_history)
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        # If user says 'lookup ticket' or similar, trigger lookup_ticket flow
        if detector.looks_like_ticket_lookup_request(choice):
            # Ask for ticket number
            return TICKET_LOOKUP_NUMBER_PROMPT, True
        elif "device" in choice:
            print(f"[Agent Controller] Decision → CHECK DEVICE for username: {username}")
            device_prompt = f"Use check_device_status with '{username}'. Display the full device details."
            action_response = await action_agent.run(device_prompt)
            return action_response.text, True
        elif "ticket" in choice:
            print(f"[Agent Controller] Decision → CREATE TICKET for username: {username}")
            history_context = "\n".join(
                f"{m['role'].upper()}: {m['content']}"
                for m in conversation_history[-HISTORY_LIMIT:]
            )
            ticket_prompt = (
                f"Conversation history:\n{history_context}\n\n"
                f"The user wants to create a support ticket for username '{username}'. "
                "Collect any missing ticket details from the conversation history and create the ticket."
            )
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        else:
            return LOOKUP_NEXT_ACTION_PROMPT, True

    # Last name received — name-based lookup
    if conversation_history and detector.last_assistant_asked_for_lookup_last_name(conversation_history):
        last_name = user_input.strip()
        first_name = detector.get_first_name_from_lookup_history(conversation_history)
        if not first_name:
            return "I couldn't retrieve the first name. Please start the lookup again.", True
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        print(f"[Agent Controller] Decision → LOOKUP by name: {first_name} {last_name}")
        lookup_prompt = (
            f"Use lookup_user with first_name='{first_name}' and last_name='{last_name}'. "
            "Display all the user details returned."
        )
        action_response = await action_agent.run(lookup_prompt)
        response_text = action_response.text
        error_indicators = ("error", "failed", "not found", "no user", "please provide")
        if not any(kw in response_text.lower() for kw in error_indicators):
            response_text = response_text.rstrip() + f"\n\n{LOOKUP_NEXT_ACTION_PROMPT}"
        return response_text, True

    # First name received — ask for last name
    if conversation_history and detector.last_assistant_asked_for_lookup_first_name(conversation_history):
        print("[Agent Controller] First name received — asking for last name")
        return LOOKUP_LAST_NAME_PROMPT, True

    # Username received — username-based lookup
    if conversation_history and detector.last_assistant_asked_for_lookup_username(conversation_history):
        username = user_input.strip()
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        print(f"[Agent Controller] Decision → LOOKUP by username: {username}")
        lookup_prompt = (
            f"Use lookup_user with username='{username}'. "
            "Display all the user details returned."
        )
        action_response = await action_agent.run(lookup_prompt)
        response_text = action_response.text
        error_indicators = ("error", "failed", "not found", "no user", "please provide")
        if not any(kw in response_text.lower() for kw in error_indicators):
            response_text = response_text.rstrip() + f"\n\n{LOOKUP_NEXT_ACTION_PROMPT}"
        return response_text, True

    # Lookup method chosen
    if conversation_history and detector.last_assistant_asked_lookup_method(conversation_history):
        choice = user_input.strip().lower()
        if "username" in choice or choice == "1":
            return LOOKUP_USERNAME_INPUT_PROMPT, True
        elif "name" in choice or choice == "2":
            return LOOKUP_FIRST_NAME_PROMPT, True
        else:
            return LOOKUP_METHOD_PROMPT, True

    # Ticket number received
    if conversation_history and detector.last_assistant_asked_for_ticket_number(conversation_history):
        ticket_id = detector.extract_ticket_id_from_input(user_input) or user_input.strip()
        if not ticket_id:
            return TICKET_LOOKUP_NUMBER_PROMPT, True
        if not action_agent:
            return "Action agent is unavailable because Azure OpenAI settings are missing.", True
        print(f"[Agent Controller] Decision → LOOKUP TICKET: {ticket_id}")
        ticket_prompt = f"Use lookup_ticket with ticket_id='{ticket_id}'. Display all the ticket details returned."
        action_response = await action_agent.run(ticket_prompt)
        return action_response.text, True

    # Ticket-by-user last name received
    if conversation_history and detector.last_assistant_asked_for_ticket_lookup_last_name(conversation_history):
        last_name = user_input.strip()
        first_name = detector.get_ticket_lookup_first_name_from_history(conversation_history)
        if first_name and last_name:
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (name): {first_name} {last_name}")
            ticket_prompt = f"Use lookup_tickets_by_user with first_name='{first_name}' and last_name='{last_name}'. Display all the tickets returned."
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        return TICKET_LOOKUP_USER_LAST_NAME_PROMPT, True

    # Ticket-by-user first name received
    if conversation_history and detector.last_assistant_asked_for_ticket_lookup_first_name(conversation_history):
        print("[Agent Controller] Decision → TICKET LOOKUP BY NAME → first name received, prompting for last name")
        return TICKET_LOOKUP_USER_LAST_NAME_PROMPT, True

    # Ticket-by-username received
    if conversation_history and detector.last_assistant_asked_for_ticket_lookup_username(conversation_history):
        identity_value, identity_kind = detector.extract_identity_value(user_input)
        if identity_value:
            lookup_username = detector.normalize_lookup_username(identity_value, identity_kind)
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (username): {lookup_username}")
            ticket_prompt = f"Use lookup_tickets_by_user with username='{lookup_username}'. Display all the tickets returned."
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        return TICKET_LOOKUP_USERNAME_PROMPT, True

    # Ticket lookup method choice
    if conversation_history and detector.last_assistant_asked_for_ticket_lookup_method(conversation_history):
        choice = user_input.strip().lower()
        if "number" in choice or choice == "1":
            return TICKET_LOOKUP_NUMBER_PROMPT, True
        elif choice == "username" or "username" in choice:
            return TICKET_LOOKUP_USERNAME_PROMPT, True
        elif "name" in choice or "user" in choice or choice == "2":
            return TICKET_LOOKUP_USER_PROMPT, True
        else:
            return TICKET_LOOKUP_METHOD_PROMPT, True

    # Ticket lookup request — extract ID or prompt
    if detector.looks_like_ticket_lookup_request(user_input):
        ticket_id = detector.extract_ticket_id_from_input(user_input)
        if ticket_id:
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKET (inline): {ticket_id}")
            ticket_prompt = f"Use lookup_ticket with ticket_id='{ticket_id}'. Display all the ticket details returned."
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        target_value, target_kind = detector.extract_ticket_lookup_target(user_input)
        if target_kind == "username":
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (inline username): {target_value}")
            ticket_prompt = f"Use lookup_tickets_by_user with username='{target_value}'. Display all the tickets returned."
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        if target_kind == "name":
            first_name, last_name = target_value
            if not action_agent:
                return "Action agent is unavailable because Azure OpenAI settings are missing.", True
            print(f"[Agent Controller] Decision → LOOKUP TICKETS BY USER (inline name): {first_name} {last_name}")
            ticket_prompt = f"Use lookup_tickets_by_user with first_name='{first_name}' and last_name='{last_name}'. Display all the tickets returned."
            action_response = await action_agent.run(ticket_prompt)
            return action_response.text, True
        by_method = detector.extract_lookup_by_keyword(user_input)
        if by_method == "username":
            print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for username")
            return TICKET_LOOKUP_USERNAME_PROMPT, True
        if by_method == "name":
            print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for first/last name")
            return TICKET_LOOKUP_USER_PROMPT, True
        if by_method == "number":
            print("[Agent Controller] Decision → TICKET LOOKUP BY → prompting for ticket number")
            return TICKET_LOOKUP_NUMBER_PROMPT, True
        return TICKET_LOOKUP_METHOD_PROMPT, True

    # Direct lookup request
    if detector.looks_like_direct_lookup_request(user_input):
        print("[Agent Controller] Decision → DIRECT LOOKUP → prompting for method")
        return LOOKUP_METHOD_PROMPT, True

    # Failed troubleshooting steps
    if detector.user_reports_failed_steps(user_input, conversation_history):
        print("[Agent Controller] Decision → FOLLOW-UP FAILURE → OFFER ESCALATION")
        return (
            "Thanks for trying those steps."
            + "\n\nWould you like me to create a support ticket for this issue?"
            + ESCALATION_SUFFIX
        ), True

    # Duplicate ticket guard
    if detector.last_assistant_warned_about_duplicate_ticket(conversation_history):
        if detector.looks_like_ticket_confirmation(user_input):
            print("[Agent Controller] Decision → DUPLICATE TICKET CONFIRMED → prompting for new issue")
            return "Please describe the new issue you'd like to open a ticket for.", True
        if user_input.strip().lower() in ("no", "no thanks", "cancel", "never mind", "nevermind", "nope"):
            return "Understood. No additional ticket will be created.", True

    if detector.looks_like_ticket_request(user_input):
        existing_ticket_id = detector.ticket_already_created_in_session(conversation_history)
        if existing_ticket_id:
            print(f"[Agent Controller] Decision → DUPLICATE TICKET GUARD (existing: {existing_ticket_id})")
            return (
                f"A ticket was already opened in this conversation (Ticket ID: {existing_ticket_id}). "
                "Would you like to open an additional ticket for a different issue? "
                "Reply 'yes' to proceed or 'no' to cancel."
            ), True

    # Delegate to the MAF Orchestrator
    response = await run_orchestrator(user_input, conversation_history)
    if escalation.should_run_escalation_check(response):
        final_response = escalation.check_escalation(response)
    else:
        final_response = response

    return final_response, True
