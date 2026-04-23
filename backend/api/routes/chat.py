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
        if not query_embedding or len(query_embedding) == 0:
            raise ValueError("Embedding model returned an empty vector.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed query: {str(e)}")

    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    
    top_chunks = []
    
    active_filename = payload.attachment_meta.get("name") if payload.attachment_meta else None

    # Use targeted Vector Search even for specific files to save reads
    # (1 query read + 1 read per result instead of 200+ reads for a large file)
    vector_query = chunks_ref.where(
        filter=FieldFilter("user_email", "==", user_email)
    ).where(
        filter=FieldFilter("status", "==", "processed")
    )
    
    if active_filename:
        vector_query = vector_query.where(filter=FieldFilter("filename", "==", active_filename))

    vector_query = vector_query.find_nearest(
        vector_field="embedding",
        query_vector=query_embedding,
        distance_measure=DistanceMeasure.COSINE,
        limit=3,
        distance_threshold=0.65, # Higher threshold for better relevance
        distance_result_field="vector_distance"
    )
    
    docs = vector_query.stream()
    scored_chunks = []

    for doc in docs:
        data = doc.to_dict()
        distance = data.get("vector_distance", 1.0)
        similarity_score = float(1.0 - distance)
        
        scored_chunks.append({
            "id": doc.id,
            "text": data.get("text", ""),
            "document_name": data.get("document_name", "Unknown"),
            "filename": data.get("filename", ""),
            "page_number": data.get("page_number", 1),
            "source_url": data.get("source_url", ""),
            "score": similarity_score,
            "doc_type": data.get("doc_type", "pdf")
        })
    
    top_chunks = scored_chunks[:3]

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
