IT Helpdesk Assistant 

This is a MVP (Minimum Viable Product) RAG Implementation for Pod 2

Steps:
- First create a file ".env" 
- Within the .env file, add the following information

AZURE_OPENAI_ENDPOINT = "https://ai-bootcamp-openai-pod2.openai.azure.com/"
AZURE_OPENAI_API_KEY = "******"
AZURE_OPENAI_DEPLOYMENT = "text-embedding-3-small"
AZURE_OPENAI_API_VERSION = "2024-02-01"


AZURE_SEARCH_ENDPOINT = "https://ai-bootcamp-search-pod2.search.windows.net"
AZURE_SEARCH_KEY = "******"
AZURE_SEARCH_INDEX = "rag-1774655785839"

- Note that AZURE_SEARCH_INDEX is subject to change.
  
- To get your AZURE_OPENAI_API_KEY, open and login to Azure Foundry/Microsoft Foundry, [LEFT PANE] Resource Management > Keys and Endpoint 
  
- To get AZURE_SEARCH_KEY, open and login to Azure AI Search, [LEFT PANE] Settings > Keys > Select either Primary or Secondary Key

- Install the requirements file with "pip install -r requirements.txt"

- Run the file with "python app.py"
 