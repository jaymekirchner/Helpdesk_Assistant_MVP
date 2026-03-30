import os
import sys
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI  # ✅ Clean import, new SDK style only

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

# ✅ Initialize AzureOpenAI client ONCE at module level (new SDK style only)
openai_client = AzureOpenAI(
    api_key=OPENAI_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=OPENAI_ENDPOINT
)

def get_search_results(query, top_k=3):
    """
    Query Azure AI Search and return top_k results.
    Tries common content fields.
    """
    try:
        results = search_client.search(query, top=top_k)
        docs = []
        for doc in results:
            for field in ["content", "text", "chunk", "chunk_text"]:
                if field in doc and doc[field]:
                    docs.append(doc[field])
                    break
            else:
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

    # ✅ System message carries the grounding instruction
    system_message = (
        "You are a helpful IT helpdesk assistant. Answer the user's question using ONLY using the context provided below. If the answer cannot be found in the context, say 'I don't have enough information to answer that based on the available documents.'\n\n"
        f"Context:\n{context}"
    )

    try:
        print(f"\n[DEBUG] Calling deployment: {OPENAI_DEPLOYMENT}")  # ✅ visibility
        response = openai_client.chat.completions.create(
            model=OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": question}  # ✅ clean, just the question
            ],
            temperature=0.2,
            max_tokens=512
        )
        answer = response.choices[0].message.content.strip()
        print(f"[DEBUG] Raw response received, length: {len(answer)} chars")  # ✅ visibility
        return answer
    except Exception as e:
        return f"Error from OpenAI: {e}"  # ✅ will now surface real errors

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