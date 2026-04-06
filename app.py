"""IT Helpdesk Assistant — entry point."""

import asyncio

from agents.controller import handle_user_message
from services.mcp_client import mcp_client, MCPClient


# Backward-compatible aliases for app_ui.py imports
_call_mcp_tool = mcp_client.call_tool
_extract_mcp_records = MCPClient.extract_records


async def main():
    print("═" * 76)
    print("  Azure RAG IT Support Agent + Microsoft Agent Framework")
    print("  Memory ✓  Clarification ✓  Multi-Turn ✓  Escalation ✓  Orchestrator ✓")
    print("  Agents: TriageAgent · KnowledgeAgent · ActionAgent")
    print("═" * 76)
    print("Commands: 'exit' to quit · 'reset' to clear history\n")
    print("\nHello I am an IT helpdesk support assistant. \n\nHow can I help you today?\n")

    conversation_history: list[dict] = []

    while True:
        user_input = input("\n> ").strip()

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        if user_input.lower() == "reset":
            conversation_history = []
            print("Conversation history cleared.")
            continue

        if not user_input:
            continue

        response, should_store = await handle_user_message(user_input, conversation_history)

        print(f"\nAssistant: {response}")

        if should_store:
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
