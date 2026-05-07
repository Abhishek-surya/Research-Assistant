import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load .env so GEMINI_API_KEY is always available regardless of launch context
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(dotenv_path=_env_path)

def get_client():
    load_dotenv(dotenv_path=_env_path, override=True)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError("GEMINI_API_KEY is not set. Please add it to backend/.env")
    print(f"[LLM] Using API Key: {api_key[:10]}...")
    return genai.Client(api_key=api_key)


# ── System instructions ───────────────────────────────────────────────────────

# Used when answering from local PDF/URL knowledge base chunks
DOCUMENT_SYSTEM_INSTRUCTION = """\
You are a highly capable AI Research Assistant. Below are your MANDATORY operating rules.

══ RULE 1 — CONTEXT IS YOUR SOURCE OF TRUTH ══
Your primary job is to extract the FULL, DETAILED information from the provided Context excerpts.
Read every sentence in the context. Do NOT skim or summarize into generic titles.
If the context says "Step 1: Release the anger by acknowledging how you feel about what happened",
you must extract that COMPLETE phrase — not just "Step 1".

══ RULE 2 — TARGET LANGUAGE ALIGNMENT ══
Your response MUST be generated entirely in the language requested by the user, regardless of the language used in the provided Context.

- ENGLISH REQUESTS: If the user explicitly asks for English (e.g., "in english", "summarize in english") OR if no specific language is requested, you MUST respond 100% in English, even if the source document is in Hindi, Kannada, etc.
- NON-ENGLISH REQUESTS: If the user asks for a non-English language (e.g., "in Hindi", "in Kannada"), you MUST respond 100% in that target language using its native script (Devanagari, Kannada, etc.). 
- STRICT ISOLATION (NO MIXING): Do not mix languages. If a specific language is requested, the entire body of your response must be in that language. Do not output English when Hindi is requested, and do not output Hindi when English is requested.
- TRANSLATION FIDELITY: Translate the full meaning and depth of the context into the requested language. Do not just translate headers.
- EXCEPTION: The final **Sources:** label and document filenames may remain in their original form since they are proper nouns/file paths.

══ RULE 3 — DEPTH & DETAIL ══
- The depth of your response MUST match the original context.
- If a step has sub-points, translate those sub-points too.
- Minimum: Each point should be 1-2 full sentences explaining the idea, not just a label.
- Never produce a response that is just a list of topic names with no substance.

══ RULE 4 — FORMATTING ══
- Use clean Markdown. Use `- ` bullet points or `1.` numbered lists for multiple points.
- Use **bold** for key terms or step names.
- Keep paragraphs short and readable.
- SOURCE CITATION RULE: Do NOT put source citations after every sentence.
  Instead, list all sources ONCE at the very end of your response in this format:
  ---
  **Sources:** DocumentName.pdf, Page X

══ RULE 5 — HONESTY (LOCAL KNOWLEDGE ONLY) ══
- THIS RULE APPLIES ONLY when answering from document context. It does NOT apply in web search mode.
- If the provided context does NOT contain the answer, state:
  "The provided context does not contain information about [topic]."
- Do NOT invent facts not present in the context.
"""

# Used when Google Search is triggered — completely isolated from document rules
SEARCH_SYSTEM_INSTRUCTION = """\
You are an AI assistant in WEB SEARCH MODE. All document-context rules are SUSPENDED.

█ ABSOLUTE RULE — SEARCH RESULTS ARE YOUR CONTEXT:
The Google Search results you receive ARE your ground truth for this query.
Treat them exactly as you would a textbook — extract and present the facts directly.

█ STRICTLY FORBIDDEN PHRASES (never output these under any circumstances):
- "The provided context does not contain"
- "I don't have information about"
- "This is not in my knowledge base"
- "No relevant information was found in the document"
If you catch yourself about to write any of these — STOP immediately and answer from search results instead.

█ YOUR TASK:
1. Use the Google Search tool to find the answer.
2. State the answer directly and confidently based on what the search returns.
3. Be concise and factual. No disclaimers, no filler phrases.
4. End with EXACTLY this two-line footer — no variation:
   ---
   **Sources:** Google Search
"""


def generate_answer(query_text: str, context_chunks: list[dict], use_search: bool = False) -> str:
    """
    Generate an answer using Gemini Flash.

    Args:
        query_text:      The user's question.
        context_chunks:  Verified high-score chunks from the knowledge base (score >= 0.82).
        use_search:      If True, switches to WEB SEARCH MODE with a completely different
                         system instruction. Document-context rules are fully suspended.
    """
    if use_search:
        # ── WEB SEARCH MODE ────────────────────────────────────────────────
        # Isolated system instruction — no document rules, no Rule 5 rejections.
        active_instruction = SEARCH_SYSTEM_INSTRUCTION
        active_prompt = f"Find and answer this question using Google Search: {query_text}"
        tools = [types.Tool(google_search=types.GoogleSearchRetrieval())]
        print(f"[LLM] Mode=WEB_SEARCH | query={query_text[:60]}")

    else:
        # ── DOCUMENT / KNOWLEDGE MODE ────────────────────────────────────
        context_text = ""
        if context_chunks:
            for i, chunk in enumerate(context_chunks, 1):
                source = chunk.get('document_name', 'Unknown Document')
                text = chunk.get('text', '')
                context_text += f"\n--- Source {i}: {source} ---\n{text}\n"

        active_instruction = DOCUMENT_SYSTEM_INSTRUCTION
        active_prompt = (
            f"Context:\n{context_text}\n\nUser Question:\n{query_text}"
            if context_text else
            f"User Question:\n{query_text}"
        )
        tools = []
        print(f"[LLM] Mode=DOCUMENT | chunks={len(context_chunks)} | query={query_text[:60]}")

    # Model chain — exact IDs as specified, no suffixes.
    # Rotates silently on 429/500; system_instruction and prompt passed to whichever is active.
    models_to_try = [
        'gemini-3.1-flash-lite-preview',
        'gemini-3-flash-preview',
        'gemini-2.5-flash-lite',
        'gemini-2.5-flash',
        'gemini-2.0-flash',
    ]

    client = get_client()
    last_error = None

    for model_name in models_to_try:
        try:
            config = types.GenerateContentConfig(
                system_instruction=active_instruction,
                temperature=0.3,
                tools=tools if tools else None,
            )
            response = client.models.generate_content(
                model=model_name,
                contents=active_prompt,
                config=config,
            )
            reply = response.text
            print(f"[LLM] Model={model_name} | search={use_search} | chars={len(reply)}")

            # ── Post-process safety net for search mode ───────────────────
            # If the model still slips a rejection phrase despite the instruction,
            # strip it so the user never sees a confusing mixed response.
            if use_search:
                FORBIDDEN_PHRASES = [
                    "the provided context does not contain",
                    "i don't have information",
                    "no relevant information was found",
                    "this is not in my knowledge",
                ]
                reply_lower = reply.lower()
                if any(p in reply_lower for p in FORBIDDEN_PHRASES):
                    # Remove the rejection sentence and keep the rest
                    lines = reply.split('\n')
                    clean_lines = [
                        ln for ln in lines
                        if not any(p in ln.lower() for p in FORBIDDEN_PHRASES)
                    ]
                    reply = '\n'.join(clean_lines).strip()
                    print(f"[LLM] Safety-net stripped rejection phrase from search response")

            return reply

        except Exception as e:
            err_str = str(e)
            last_error = err_str
            is_rate_limit = (
                "429" in err_str
                or "RESOURCE_EXHAUSTED" in err_str
                or "quota" in err_str.lower()
            )
            is_unavailable = (
                "503" in err_str
                or "unavailable" in err_str.lower()
                or "overloaded" in err_str.lower()
            )

            if is_rate_limit:
                print(f"[LLM] ⚠️ 429 rate limit on {model_name} — sleeping 2s then trying next")
                time.sleep(2)
            elif is_unavailable:
                print(f"[LLM] ⚠️ 503 unavailable on {model_name} — trying next model")
            else:
                print(f"[LLM] ❌ {model_name} error ({type(e).__name__}): {err_str[:120]}")

            continue

    # All models in chain exhausted — return a clean user-facing message
    print(f"[LLM] ❌ All models exhausted. Last error: {last_error}")
    return (
        "⚠️ **Server is currently at capacity (API Rate Limit).**\n\n"
        "Please **retry your message in 30 seconds**.\n"
        "All available AI models are temporarily rate-limited."
    )
