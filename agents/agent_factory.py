"""Factory for MAF agents (Triage, Knowledge, Action)."""

import logging

from config.settings import (
    OPENAI_ENDPOINT,
    OPENAI_KEY,
    OPENAI_DEPLOYMENT,
    OPENAI_API_VERSION,
    OpenAIChatCompletionClient,
)
from prompts.triage import MAF_TRIAGE_INSTRUCTIONS
from prompts.knowledge import MAF_KNOWLEDGE_INSTRUCTIONS
from prompts.action import MAF_ACTION_INSTRUCTIONS
from agents.tool_registry import ALL_TOOLS

logger = logging.getLogger(__name__)


def _build_client():
    if not all([OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT, OpenAIChatCompletionClient]):
        logger.warning("OpenAI settings incomplete — cannot build client")
        return None
    return OpenAIChatCompletionClient(
        model=OPENAI_DEPLOYMENT,
        azure_endpoint=OPENAI_ENDPOINT,
        api_version=OPENAI_API_VERSION,
        api_key=OPENAI_KEY,
    )


def create_triage_agent():
    client = _build_client()
    if client is None:
        logger.warning("TriageAgent not created — client unavailable")
        return None
    agent = client.as_agent(
        name="TriageAgent",
        instructions=MAF_TRIAGE_INSTRUCTIONS,
        tools=[],
    )
    logger.info("TriageAgent created successfully")
    return agent


def create_knowledge_agent():
    client = _build_client()
    if client is None:
        logger.warning("KnowledgeAgent not created — client unavailable")
        return None
    agent = client.as_agent(
        name="KnowledgeAgent",
        instructions=MAF_KNOWLEDGE_INSTRUCTIONS,
        tools=[],
    )
    logger.info("KnowledgeAgent created successfully")
    return agent


def create_action_agent():
    client = _build_client()
    if client is None:
        logger.warning("ActionAgent not created — client unavailable")
        return None
    agent = client.as_agent(
        name="ActionAgent",
        instructions=MAF_ACTION_INSTRUCTIONS,
        tools=ALL_TOOLS,
    )
    logger.info("ActionAgent created successfully with %d tool(s)", len(ALL_TOOLS))
    return agent


# Module-level singletons
triage_agent = create_triage_agent()
knowledge_agent = create_knowledge_agent()
action_agent = create_action_agent()
