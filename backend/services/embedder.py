"""
Embedding service using HuggingFace Serverless Inference API.
Uses the official huggingface_hub client for better reliability.
Output dimensionality: 384
"""
import os
import time
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
_client = None

def _get_client():
    global _client
    if _client is None:
        load_dotenv(dotenv_path=_env_path, override=True)
        hf_token = os.environ.get("HF_API_TOKEN", "").strip()
        _client = InferenceClient(
            model="sentence-transformers/all-MiniLM-L6-v2",
            token=hf_token if hf_token and hf_token != "your_hf_token_here" else None
        )
    return _client

def _embed_with_retry(text_or_texts):
    client = _get_client()
    
    for attempt in range(5):
        try:
            # feature_extraction returns the vectors directly
            embeddings = client.feature_extraction(text_or_texts)
            print(f"[EMBEDDER] HuggingFace embedding generated successfully.")
            return embeddings
        except Exception as e:
            err_msg = str(e)
            if "503" in err_msg or "loading" in err_msg.lower():
                print(f"[EMBEDDER] Model is loading... waiting 15s (Attempt {attempt+1}/5)")
                time.sleep(15)
                continue
            elif "429" in err_msg or "rate limit" in err_msg.lower():
                print(f"[EMBEDDER] Rate limited. Waiting 10s...")
                time.sleep(10)
                continue
            else:
                print(f"[EMBEDDER] Error: {err_msg}")
                raise e
    raise Exception("HuggingFace Inference failed after maximum retries.")


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional vector embedding.
    """
    if not text:
        return []
    
    result = _embed_with_retry(text)
    
    # Ensure result is a list of floats (not numpy types)
    import numpy as np
    if hasattr(result, "tolist"):
        data = result.tolist()
    else:
        data = result
        
    # If it's a list of lists, take the first one
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
        data = data[0]
        
    # Force convert every item to standard python float
    return [float(x) for x in data]


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate batch vector embeddings for exactly 384 dimensions.
    """
    if not texts:
        return []
        
    result = _embed_with_retry(texts)
    
    # Ensure result is a list of lists of standard python floats
    import numpy as np
    if hasattr(result, "tolist"):
        data = result.tolist()
    else:
        data = result
        
    return [[float(x) for x in sublist] for sublist in data]
