import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from firebase_admin import firestore

# Load .env so GEMINI_API_KEY is always available regardless of launch context
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(dotenv_path=_env_path, override=True)

_client = None

def get_client():
    global _client
    if not _client:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError("GEMINI_API_KEY is not set. Please add it to backend/.env")
        _client = genai.Client(api_key=api_key)
    return _client

def generate_answer(query_text: str, context_chunks: list[dict]) -> str:
    """
    Generate an answer using Gemini Flash based strictly on the provided context chunks.
    """
    if not context_chunks:
        return "I'm sorry, but I do not have any relevant information in your Knowledge Base to answer that question."

    # Format the retrieved context
    context_text = ""
    for i, chunk in enumerate(context_chunks, 1):
        source = chunk.get('document_name', 'Unknown Document')
        text = chunk.get('text', '')
        context_text += f"\n--- Source {i}: {source} ---\n{text}\n"

    # Define instructions that prioritize your documents but allow Google Search as a backup
    system_instruction = (
        "You are a highly helpful and precise AI Research Assistant. "
        "Your primary task is to answer the user's question based on the provided Context excerpts. "
        "If the Context excerpts do NOT contain the answer, you should use the Google Search tool to find reliable, up-to-date information from the web.\n\n"
        "FORMATTING INSTRUCTIONS:\n"
        "- ALWAYS use markdown formatting for readability.\n"
        "- Use bullet points `- ` or numbered lists `1. ` for steps, options, and lists.\n"
        "- Use **bold text** to highlight key terms and concepts.\n"
        "- Keep paragraphs short and concise. NEVER output a solid wall of text.\n"
        "- When possible, cite the Source document names inline (e.g., `(Source: DocumentName.pdf)`)."
    )

    prompt = f"Context:\n{context_text}\n\nUser Question:\n{query_text}"

    # Get dynamic model name from Firestore
    model_name = "gemini-2.5-flash" # fallback
    try:
        db = firestore.client()
        docs = db.collection("models").limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            # Try a few common field names, otherwise try document ID
            model_name = data.get("name") or data.get("model_name") or data.get("modelId") or doc.id
            break
    except Exception as e:
        print(f"Warning: Failed to fetch model name from Firebase, using fallback. Error: {e}")

    # Call Gemini
    client = get_client()
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1, 
                tools=[types.Tool(google_search=types.GoogleSearchRetrieval())]
            ),
        )
        return response.text
    except Exception as e:
        return f"Error generating answer: {str(e)}"
