import os
import sys
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import openai

# Load environment variables from .env file
load_dotenv()

# Azure Search configuration
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX")

# Azure OpenAI configuration
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# # print all env vars for debugging
# print("Environment Variables:")
# print(f"SEARCH_ENDPOINT: {SEARCH_ENDPOINT}")
# print(f"SEARCH_KEY: {'***' if SEARCH_KEY else None}")
# print(f"SEARCH_INDEX: {SEARCH_INDEX}")  
# print(f"OPENAI_ENDPOINT: {OPENAI_ENDPOINT}")
# print(f"OPENAI_KEY: {'***' if OPENAI_KEY else None}")
# print(f"OPENAI_DEPLOYMENT: {OPENAI_DEPLOYMENT}")

# Validate environment variables
if not all([SEARCH_ENDPOINT, SEARCH_KEY, SEARCH_INDEX, OPENAI_ENDPOINT, OPENAI_KEY, OPENAI_DEPLOYMENT]):
    print("Missing required environment variables. Please check your .env file.")
    sys.exit(1)

# Initialize Azure Search client
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_KEY)
)

# Initialize OpenAI client
openai.api_type = "azure"
openai.api_base = OPENAI_ENDPOINT
openai.api_key = OPENAI_KEY
openai.api_version = "2024-02-15-preview"

def get_search_results(query, top_k=3):
    """
    Query Azure AI Search and return top_k results.
    Tries common content fields.
    """
    try:
        results = search_client.search(query, top=top_k)
        docs = []
        for doc in results:
            # Try to extract content from common fields
            for field in ["content", "text", "chunk", "chunk_text"]:
                if field in doc and doc[field]:
                    docs.append(doc[field])
                    break
            else:
                # Fallback: add stringified doc
                docs.append(str(doc))
        return docs
    except Exception as e:
        print(f"Error querying Azure Search: {e}")
        return []

def get_grounded_answer(question, context_docs):
    """
    Send context and question to Azure OpenAI and return the answer.
    """
    context = "\n---\n".join(context_docs)
    prompt = f"""
You are an AI assistant. Use ONLY the provided context to answer the user's question. If the answer is not in the context, say you don't know.

Context:
{context}

Question: {question}
Answer:"""
    try:
        client = openai.AzureOpenAI(
            api_key=OPENAI_KEY,
            api_version="2024-02-15-preview",
            azure_endpoint=OPENAI_ENDPOINT
        )
        response = client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=512
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error from OpenAI: {e}"

def main():
    print("Azure RAG MVP (no LangChain)")
    print("Type your question (or 'exit' to quit):")
    while True:
        question = input("\n> ").strip()
        if question.lower() in ("exit", "quit"): 
            print("Goodbye!")
            break
        if not question:
            continue
        print("\nSearching for relevant documents...")
        docs = get_search_results(question, top_k=5)
        if not docs:
            print("No relevant documents found.")
            continue
        print(f"Found {len(docs)} relevant document(s).\nPrinting retrieved chunks:")
        for i, doc in enumerate(docs, 1):
            print(f"\n--- Chunk {i} ---\n{doc}")
        print("\nGenerating answer...")
        answer = get_grounded_answer(question, docs)
        print(f"\nAnswer:\n{answer}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")