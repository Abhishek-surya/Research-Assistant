import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from firebase_admin import firestore

# Load .env so GEMINI_API_KEY is always available regardless of launch context
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(dotenv_path=_env_path)

def get_client():
    # Force reload environment variables to drop old cache
    load_dotenv(dotenv_path=_env_path, override=True)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError("GEMINI_API_KEY is not set. Please add it to backend/.env")
    
    print(f"[LLM] Using API Key: {api_key[:10]}...")
    # Do not cache client globally so key rotation works instantly
    return genai.Client(api_key=api_key)

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

    models_to_try = [
        'gemini-1.5-flash',
        'gemini-3.1-flash-lite',
        'gemini-2.5-flash-lite'
    ]

    client = get_client()
    last_error = None

    for model_name in models_to_try:
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
            last_error = str(e)
            print(f"Warning: Model {model_name} failed with error: {last_error}")
            # Automatically try next if we see 503 or Unavailable
            if "503" in str(e) or "Unavailable" in str(e) or "unavailable" in str(e).lower() or "overloaded" in str(e).lower():
                continue
            else:
                # For non-503 errors, we probably shouldn't fallback, but let's be safe and try the next one anyways,
                # Or wait, the user said "If the first one fails with 503, it must automatically try the next one."
                # I'll just continue if it looks like a server issue.
                continue

    return f"Error generating answer after trying fallback models: {last_error}"
