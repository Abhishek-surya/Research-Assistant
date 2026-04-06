from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.deps import verify_token
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from services.embedder import generate_embedding
from services.llm import generate_answer
import math
import uuid
from datetime import datetime, timezone

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    active_context: Optional[str] = None # The raw text context
    attachment_meta: Optional[dict] = None # Metadata (name, type)



@router.post("/chat")
async def chat_with_docs(payload: ChatRequest, user_token: dict = Depends(verify_token)):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    user_query = payload.message.strip()
    if not user_query and not payload.active_context:
        raise HTTPException(status_code=400, detail="Message/Context cannot be empty")

    context_text = payload.active_context or ""
    
    # 1. Generate embedding for the full query (User + Context)
    query_for_search = user_query
    if context_text:
        query_for_search += f"\n\nContext Fragment:\n{context_text}"

    try:
        query_embedding = generate_embedding(query_for_search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed query: {str(e)}")

    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

    # 2. Fetch nearest chunks using native Firestore Vector Search
    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    
    # Apply vector search on filtered collection. 
    # Similarity Threshold 0.35 means max COSINE distance is 0.65
    vector_query = chunks_ref.where(
        filter=FieldFilter("user_email", "==", user_email)
    ).where(
        filter=FieldFilter("status", "==", "processed")
    ).find_nearest(
        vector_field="embedding",
        query_vector=query_embedding,
        distance_measure=DistanceMeasure.COSINE,
        limit=5,
        distance_threshold=0.65,
        distance_result_field="vector_distance"
    )
    docs = vector_query.stream()

    top_chunks = []
    for doc in docs:
        data = doc.to_dict()
        distance = data.get("vector_distance", 1.0)
        similarity_score = 1.0 - distance
        
        top_chunks.append({
            "id": doc.id,
            "text": data.get("text", ""),
            "document_name": data.get("document_name", "Unknown"),
            "filename": data.get("filename", ""),
            "page_number": data.get("page_number", 1),
            "source_url": data.get("source_url", ""),
            "score": similarity_score,
            "doc_type": data.get("doc_type", "pdf")
        })

    # 5. Generate Answer using Gemini LLM
    llm_reply = generate_answer(query_for_search, top_chunks)

    # 6. Persist Q&A turn to Firestore chat_history
    session_id = payload.session_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db.collection("chat_history").add({
        "session_id": session_id,
        "user_email": user_email,
        "query": user_query,
        "attachment": payload.attachment_meta,
        "reply": llm_reply,
        "timestamp": now,
        # Store a short title from the first 60 chars of the query
        "title": user_query[:60].strip() or "New Chat",
    })

    return {
        "reply": llm_reply,
        "session_id": session_id,
        "context_chunks": top_chunks
    }
