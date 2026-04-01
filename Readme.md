IT Helpdesk Assistant 

This is a MVP (Minimum Viable Product) RAG Implementation for Pod 2

Steps:
- First create a file ".env" 
- Within the .env file, add the following information

  - AZURE_OPENAI_ENDPOINT = "https://ai-bootcamp-openai-pod2.openai.azure.com/"
  - AZURE_OPENAI_API_KEY = "******"
  - AZURE_OPENAI_DEPLOYMENT = "gpt-4o-mini"
  - AZURE_OPENAI_API_VERSION = "2024-02-01"


  - AZURE_SEARCH_ENDPOINT = "https://ai-bootcamp-search-pod2.search.windows.net"
  - AZURE_SEARCH_KEY = "******"
  - AZURE_SEARCH_INDEX = "rag-1774655785839"

- Note that AZURE_SEARCH_INDEX is subject to change.
  
- To get your AZURE_OPENAI_API_KEY, open and login to Azure Foundry/Microsoft Foundry, [LEFT PANE] Resource Management > Keys and Endpoint 
  
- To get AZURE_SEARCH_KEY, open and login to Azure AI Search, [LEFT PANE] Settings > Keys > Select either Primary or Secondary Key.

- Optional (Recommended) step: Create a Python Virtual Environment with in your TERMINAL
  - "python3 -m venv venv"
- Access the Python Virtual Env as follows:
  - Windows:
    - venv\Scripts\activate.bat
  - MacOs/Linux:
      - source venv/bin/activate

- Install the requirements file with "pip install -r requirements.txt" in your TERMINAL

- Run the file with "python app.py" in your TERMINAL
 
------------------------------------------------------------------------------------------------------
HOW TO SET UP THE MCP SERVER 
------------------------------------------------------------------------------------------------------

1. Check if Node.js is installed:
bashnode --version
npm --version
npx --version
If any of those fail, install Node.js:

2. Install Node.js (pick your OS):
macOS:
bashbrew install node
Ubuntu/Debian:
bashcurl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
Windows: Download the installer from nodejs.org

3. If Node IS installed but npx still isn't found, it's a PATH issue. Find where npx lives and add it:
bashwhich npx          # or: whereis npx
Then add it to your shell config (~/.bashrc, ~/.zshrc, etc.):
bashexport PATH="/path/to/node/bin:$PATH"
source ~/.zshrc    # or ~/.bashrc

4. Then retry:
bashmcp dev server.py

Restart your terminal after any install — that's the most commonly missed step. The MCP CLI needs npx on the PATH in the same shell session where you're running it.