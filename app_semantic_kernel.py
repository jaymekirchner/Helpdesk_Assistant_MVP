"""
Azure RAG IT Support Agent using Microsoft Semantic Kernel
Refactored from layer-based architecture to plugin-based architecture
"""

import os
import sys
import json
import asyncio
from dotenv import load_dotenv

# Semantic Kernel Imports
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function

# Azure Search Imports
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

load_dotenv()

# ════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

if not all([SEARCH_ENDPOINT, SEARCH_KEY, SEARCH_INDEX, OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT]):
    print("Missing environment variables. Check your .env file.")
    sys.exit(1)

# ════════════════════════════════════════════════════
# PLUGINS
# ════════════════════════════════════════════════════

class QueryBuilderPlugin:
    @kernel_function(description="Enrich search query from history", name="build_query")
    async def build_retrieval_query(self, user_input: str, history: ChatHistory, kernel: Kernel) -> str:
        if len(history) <= 1: # Only system message
            return user_input

        svc = kernel.get_service("default")
        settings = AzureChatPromptExecutionSettings(service_id="default", max_tokens=50, temperature=0.0)
        
        # Temporary history for enrichment task
        enrich_history = ChatHistory()
        enrich_history.add_system_message("Output ONLY a concise search query based on conversation history. Keywords only.")
        for msg in history:
            role_str = str(msg.role).lower().replace("authorrole.", "")
            if "system" in role_str:
                enrich_history.add_system_message(msg.content)
            elif "user" in role_str:
                enrich_history.add_user_message(msg.content)
            elif "assistant" in role_str:
                enrich_history.add_assistant_message(msg.content)
        enrich_history.add_user_message(f"Latest input: {user_input}")

        response = await svc.get_chat_message_contents(chat_history=enrich_history, settings=settings)
        return str(response[0].content).strip()

class RetrievalPlugin:
    def __init__(self, client):
        self.client = client

    @kernel_function(description="Search Azure Search index", name="get_documents")
    def get_search_results(self, query: str, top_k: int = 3) -> str:
        try:
            results = self.client.search(query, top=top_k)
            docs = [doc.get("content", str(doc)) for doc in results]
            return "\n---\n".join(docs)
        except Exception as e:
            return f"Error during retrieval: {e}"

class TriagePlugin:
    @kernel_function(description="Check if query is vague", name="check_vagueness")
    async def is_query_vague(self, question: str, kernel: Kernel) -> str:
        svc = kernel.get_service("default")
        settings = AzureChatPromptExecutionSettings(service_id="default", max_tokens=100, temperature=0.0)

        prompt = (
            "You are an IT support triage assistant. Decide if the user's question "
            "is too vague to answer without more detail.\n\n"
            "A query is vague ONLY if it is missing critical information AND cannot be answered "
            "with general guidance or by asking follow-up questions.\n\n"
            "Examples of vague (require clarification): 'Help me', 'Something is wrong', "
            "'I have a problem'\n\n"
            "Examples of specific enough (can proceed): 'Do I have Outlook installed?', "
            "'How do I check system info?', 'My VPN isn't working', "
            "'I can't connect to wifi', 'How do I reset my password?'\n\n"
            "Simple questions about common IT tasks should NOT be marked as vague - "
            "we can provide general guidance and ask for OS details if needed.\n\n"
            "Return JSON: {\"vague\": true, \"clarifying_question\": \"Your single follow-up question here\"} "
            "or {\"vague\": false, \"clarifying_question\": null}\n\n"
            "No explanation. No markdown. JSON only."
        )

        temp_history = ChatHistory(system_message=prompt)
        temp_history.add_user_message(question)

        response = await svc.get_chat_message_contents(chat_history=temp_history, settings=settings)
        return str(response[0].content).strip()

class UtilityPlugin:
    """Additional utility tools for IT support"""

    @kernel_function(description="Check system information and provide basic troubleshooting steps", name="system_info")
    async def get_system_info_help(self, os_type: str = "unknown") -> str:
        """Provide OS-specific system information commands"""
        if os_type.lower() == "windows":
            return "Run 'systeminfo' in Command Prompt or 'Get-ComputerInfo' in PowerShell to check system details."
        elif os_type.lower() == "mac":
            return "Run 'system_profiler SPSoftwareDataType SPHardwareDataType' in Terminal to check system information."
        elif os_type.lower() == "linux":
            return "Run 'uname -a && lsb_release -a' to check system information."
        else:
            return "Please specify your operating system (Windows/Mac/Linux) for accurate system information commands."

    @kernel_function(description="Generate network diagnostic commands", name="network_diagnostics")
    async def network_diagnostics(self, issue_type: str = "connectivity") -> str:
        """Provide network troubleshooting commands based on issue type"""
        commands = {
            "connectivity": "ping 8.8.8.8 (test internet), ping google.com (test DNS), tracert google.com (trace route)",
            "wifi": "Check network settings, run 'ipconfig /renew' (Windows) or 'sudo dhclient -r && sudo dhclient' (Mac/Linux)",
            "slow": "Run speed test at speedtest.net, check Task Manager/Network tab, close bandwidth-heavy applications"
        }
        return commands.get(issue_type.lower(), "Please describe your network issue (connectivity/wifi/slow) for specific guidance.")

    @kernel_function(description="Provide password reset instructions", name="password_reset")
    async def password_reset_guide(self, account_type: str = "work") -> str:
        """Guide users through password reset process"""
        if account_type.lower() == "work":
            return "1. Visit the company password reset portal\\n2. Click 'Forgot Password'\\n3. Enter your work email\\n4. Follow the verification steps\\n5. Create a strong new password\\n6. Contact IT if you don't receive the reset email"
        elif account_type.lower() == "email":
            return "1. Go to your email provider's login page\\n2. Click 'Forgot Password' or 'Reset Password'\\n3. Enter your email address\\n4. Check your recovery email/phone\\n5. Follow the security verification\\n6. Set a new password"
        else:
            return "Please specify if this is for work account or personal email."

    @kernel_function(description="Check software installation status", name="software_check")
    async def check_software_installation(self, software_name: str, os_type: str = "windows") -> str:
        """Check if software is installed and provide installation guidance"""
        checks = {
            "windows": f'Run "where {software_name}" in Command Prompt, or check Programs & Features in Control Panel',
            "mac": f'Run "which {software_name}" in Terminal, or check Applications folder',
            "linux": f'Run "which {software_name}" or "dpkg -l | grep {software_name}" in terminal'
        }
        return f"To check if {software_name} is installed on {os_type}:\\n{checks.get(os_type.lower(), 'Please specify your OS')}\\n\\nIf not installed, download from the official website or contact IT for assistance."

async def main():
    # 1. Initialize Kernel
    kernel = Kernel()
    kernel.add_service(AzureChatCompletion(
        service_id="default",
        api_key=OPENAI_KEY,
        endpoint=OPENAI_ENDPOINT,
        deployment_name=OPENAI_DEPLOYMENT,
    ))

    # 2. Register Plugins
    search_client = SearchClient(SEARCH_ENDPOINT, SEARCH_INDEX, AzureKeyCredential(SEARCH_KEY))
    kernel.add_plugin(QueryBuilderPlugin(), plugin_name="QueryBuilder")
    kernel.add_plugin(RetrievalPlugin(search_client), plugin_name="Retriever")
    kernel.add_plugin(TriagePlugin(), plugin_name="Triage")
    kernel.add_plugin(UtilityPlugin(), plugin_name="Utility")

    # 3. Chat Loop
    history = ChatHistory(system_message=(
        "You are a helpful IT Support Assistant. Use the provided context and available tools to give practical, "
        "step-by-step guidance. If the user doesn't specify their OS, provide instructions for common platforms "
        "(Windows, Mac, Linux) or ask for clarification. Be proactive in offering solutions and use the available "
        "tools when appropriate. Focus on being helpful rather than asking too many questions."
    ))
    print("IT Support Agent ready. Type 'exit' to quit.")

    while True:
        user_input = input("\nUser: ")
        if user_input.lower() in ["exit", "quit"]: break

# Step A: Triage (Optional - only block truly meaningless questions)
        triage_result_raw = await kernel.invoke(plugin_name="Triage", function_name="check_vagueness", question=user_input, kernel=kernel)
        triage_data = json.loads(str(triage_result_raw))

        # Only ask for clarification on extremely vague questions like "help me" or single words
        extremely_vague = (
            user_input.lower().strip() in ["help", "help me", "please help", "i need help"] or
            len(user_input.strip().split()) <= 2 and not any(word in user_input.lower() for word in ["outlook", "vpn", "wifi", "password", "system", "network", "software", "install"])
        )

        if triage_data.get("vague") and extremely_vague:
            print(f"Assistant: {triage_data['clarifying_question']}")
            continue

        # Step B: Build Query & Retrieve
        enriched_query = await kernel.invoke(plugin_name="QueryBuilder", function_name="build_query", user_input=user_input, history=history, kernel=kernel)
        docs = await kernel.invoke(plugin_name="Retriever", function_name="get_documents", query=str(enriched_query))

        # Step C: Check for direct tool usage based on question patterns
        tool_result = None
        user_input_lower = user_input.lower()

        # Software check tool
        if ("software check" in user_input_lower or
            ("check" in user_input_lower and any(word in user_input_lower for word in ["install", "installed", "have", "outlook", "office", "word", "excel"])) or
            (len(user_input.strip().split()) == 1 and user_input_lower in ["outlook", "office", "word", "excel", "chrome", "firefox"])):
            software_name = user_input.strip()
            if software_name.lower() == "outlook":
                tool_result = await kernel.invoke(plugin_name="Utility", function_name="software_check", software_name=software_name)

        # System info tool
        elif any(word in user_input_lower for word in ["system info", "system information", "computer info", "specs", "hardware"]):
            tool_result = await kernel.invoke(plugin_name="Utility", function_name="system_info")

        # Network diagnostics tool
        elif any(word in user_input_lower for word in ["network", "wifi", "internet", "connect", "connection", "ping"]):
            tool_result = await kernel.invoke(plugin_name="Utility", function_name="network_diagnostics")

        # Password reset tool
        elif any(word in user_input_lower for word in ["password", "reset", "forgot", "login", "account"]):
            tool_result = await kernel.invoke(plugin_name="Utility", function_name="password_reset")

        # Step D: Final Answer with Tool Integration

        tool_context = f"""
AVAILABLE TOOLS - Can be called directly for specific queries:
- system_info(os_type): Get OS-specific system information commands
- network_diagnostics(issue_type): Network troubleshooting
- password_reset(account_type): Password reset instructions
- software_check(software_name, os_type): Check software installation

{f"TOOL RESULT: {tool_result}" if tool_result else "No specific tool was triggered for this query."}
"""

        history.add_user_message(f"Context: {docs}\n\n{tool_context}\n\nUser Question: {user_input}")
        svc = kernel.get_service("default")
        final_response = await svc.get_chat_message_contents(chat_history=history, settings=AzureChatPromptExecutionSettings(service_id="default"))

        answer = final_response[0].content
        print(f"Assistant: {answer}")
        history.add_assistant_message(answer)

if __name__ == "__main__":
    asyncio.run(main())
