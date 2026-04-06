"""MAF Orchestrator — routes user requests to the right agent (Triage → Knowledge / Action)."""

import json

from config.constants import HISTORY_LIMIT, KNOWLEDGE_TOP_K, ESCALATION_SUFFIX
from services.retrieval_engine import RetrievalEngine
from services.escalation_service import EscalationService
from agents.agent_factory import triage_agent, knowledge_agent, action_agent
from utils.conversation_detector import ConversationDetector

retrieval = RetrievalEngine()
escalation = EscalationService()
detector = ConversationDetector()


async def run_orchestrator(user_input: str, conversation_history: list) -> str:
    """Route user request through Triage → Knowledge or Action agent."""
    print("\n[Orchestrator] Starting triage...")

    history_context = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in conversation_history[-HISTORY_LIMIT:]
    )
    triage_prompt = (
        f"Conversation so far:\n{history_context}\n\nLatest message: {user_input}"
        if history_context else user_input
    )

    # ── Step 1: Triage ──────────────────────────────────────────
    if triage_agent is None:
        print("[Orchestrator] Triage agent unavailable — defaulting to knowledge route")
        triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}
    else:
        try:
            triage_response = await triage_agent.run(triage_prompt)
            triage_raw = triage_response.text.strip()
            print(f"[Orchestrator] Triage: {triage_raw}")
            triage_data = json.loads(triage_raw)
        except Exception as e:
            print(f"[Orchestrator] Triage failed: {e} — defaulting to knowledge route")
            triage_data = {"route_to": "knowledge", "urgency": "medium", "category": "General"}

    route_to = triage_data.get("route_to", "knowledge")
    urgency = triage_data.get("urgency", "medium")
    category = triage_data.get("category", "General")

    if detector.looks_like_ticket_request(user_input):
        print("[Orchestrator] Overriding route to ACTION due to explicit ticket request.")
        route_to = "action"

    explicit_action_intent = detector.looks_like_tool_request(user_input) or detector.looks_like_ticket_request(user_input)
    if route_to == "action" and not explicit_action_intent:
        print("[Orchestrator] Action route kept from TRIAGE (weak explicit signal, context-based action intent)")

    print(f"[Orchestrator] Route → {route_to.upper()} | Urgency: {urgency} | Category: {category}")

    # ── Step 2: Clarification ────────────────────────────────────
    if route_to == "clarify":
        return triage_data.get(
            "clarifying_question",
            "Could you provide more details about the issue?",
        )

    # ── Step 3a: Knowledge Agent ─────────────────────────────────
    if route_to == "knowledge":
        print("[Orchestrator] Dispatching → KnowledgeAgent")
        if knowledge_agent is None:
            return (
                "Knowledge agent is unavailable because backend AI components failed to initialize. "
                "Please check app settings and startup logs."
            )

        enriched_query = retrieval.build_retrieval_query(user_input, conversation_history)
        docs = retrieval.get_search_results(enriched_query, top_k=KNOWLEDGE_TOP_K)

        error_code = RetrievalEngine.extract_error_code(user_input)
        if error_code and docs and not RetrievalEngine.docs_contain_error_code(docs, error_code):
            fallback_query = f"error code {error_code} {user_input}"
            print(f"[Orchestrator] Retrying retrieval with error-code fallback query: '{fallback_query}'")
            fallback_docs = retrieval.get_search_results(fallback_query, top_k=KNOWLEDGE_TOP_K)
            if fallback_docs:
                docs = fallback_docs

        if error_code and not RetrievalEngine.docs_contain_error_code(docs, error_code):
            print(f"[Orchestrator] Error code {error_code} not found in retrieved docs — treating as KB miss")
            return (
                "I do not know based on the knowledge base. "
                "Would you like me to connect to IT Support?"
            )

        if not docs:
            print("[Orchestrator] No docs found — skipping KnowledgeAgent")
            return (
                "I do not know based on the knowledge base. "
                "Would you like me to connect to IT Support?"
            )

        numbered_docs = "\n\n".join(
            f"[Document {i}]\n{doc.strip()}" for i, doc in enumerate(docs, 1)
        )
        knowledge_prompt = (
            f"{f'Conversation history:{chr(10)}{history_context}{chr(10)}{chr(10)}' if history_context else ''}"
            f"User question: {user_input}\n\n"
            f"RETRIEVED DOCUMENTS:\n{numbered_docs}"
        )
        print(f"[Orchestrator] Passing {len(docs)} doc(s) to KnowledgeAgent")
        try:
            knowledge_response = await knowledge_agent.run(knowledge_prompt)
            return knowledge_response.text.strip()
        except Exception as e:
            return f"Knowledge base lookup failed: {e}"

    # ── Step 3b: Action Agent ─────────────────────────────────────
    if route_to == "action":
        print("[Orchestrator] Dispatching → ActionAgent")
        if action_agent is None:
            return "Action agent is unavailable because Azure OpenAI settings are missing or invalid."
        try:
            action_prompt = (
                f"Conversation history:\n{history_context}\n\nUser message: {user_input}"
                if history_context else user_input
            )
            action_response = await action_agent.run(action_prompt)
            return action_response.text.strip()
        except Exception as e:
            return f"Action execution failed: {e}"

    return "I was unable to process your request. Please try again."
