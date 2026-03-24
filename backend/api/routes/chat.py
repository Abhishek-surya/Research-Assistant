from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.deps import verify_token
from firebase_admin import firestore
from services.embedder import generate_embedding
from services.llm import generate_answer
import math
import uuid
from datetime import datetime, timezone

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)

@router.post("/chat")
async def chat_with_docs(payload: ChatRequest, user_token: dict = Depends(verify_token)):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    query_text = payload.message.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # 1. Generate embedding for the query
    try:
        query_embedding = generate_embedding(query_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed query: {str(e)}")

    # 2. Fetch all processed chunks for the user
    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    docs = chunks_ref.where("user_email", "==", user_email).where("status", "==", "processed").stream()

    scored_chunks = []
    for doc in docs:
        data = doc.to_dict()
        doc_embedding = data.get("embedding")
        if not doc_embedding:
            continue
        
        # 3. Compute similarity
        score = cosine_similarity(query_embedding, doc_embedding)
        
        scored_chunks.append({
            "id": doc.id,
            "text": data.get("text", ""),
            "document_name": data.get("document_name", "Unknown"),
            "filename": data.get("filename", ""),
            "page_number": data.get("page_number", 1),
            "source_url": data.get("source_url", ""),
            "score": score,
            "doc_type": data.get("doc_type", "pdf")
        })

    # 4. Filter low-confidence chunks, sort descending, take Top 5
    SIMILARITY_THRESHOLD = 0.35
    relevant_chunks = [c for c in scored_chunks if c["score"] >= SIMILARITY_THRESHOLD]
    relevant_chunks.sort(key=lambda x: x["score"], reverse=True)
    top_chunks = relevant_chunks[:5]

    # 5. Generate Answer using Gemini LLM
    llm_reply = generate_answer(query_text, top_chunks)

    # 6. Persist Q&A turn to Firestore chat_history
    session_id = payload.session_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db.collection("chat_history").add({
        "session_id": session_id,
        "user_email": user_email,
        "query": query_text,
        "reply": llm_reply,
        "timestamp": now,
        # Store a short title from the first 60 chars of the query
        "title": query_text[:60].strip(),
    })

    return {
        "reply": llm_reply,
        "session_id": session_id,
        "context_chunks": top_chunks
    }
