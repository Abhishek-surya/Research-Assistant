"""
Embedding service using Google Gemini text-embedding-004 model.
Uses the new google-genai SDK (google-generativeai is deprecated).
"""
import os
from dotenv import load_dotenv

# Resolve .env path absolutely regardless of working directory
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(dotenv_path=_env_path)

from google import genai
from google.genai import types

_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is not set. Please add it to backend/.env"
            )
        _client = genai.Client(api_key=api_key)
    return _client


def generate_embedding(text: str) -> list[float]:
    """
    Generate a vector embedding using Google's gemini-embedding-001 model.
    Returns a list of 1536 floats (truncated from 3072 via MRL).
    Kept under Firestore's 2000-element array size limit.
    """
    client = _get_client()
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=1536
        )
    )
    return list(response.embeddings[0].values)


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate vector embeddings for a batch of strings using Google's gemini-embedding-001 model.
    """
    if not texts:
        return []
        
    client = _get_client()
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=1536
        )
    )
    return [list(e.values) for e in response.embeddings]
