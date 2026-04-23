from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.deps import verify_token
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from services.embedder import generate_embedding
from services.llm import generate_answer
import uuid
import re
from datetime import datetime, timezone

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    active_context: Optional[str] = None
    attachment_meta: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

STOP_WORDS = {
    "please", "can", "you", "tell", "me", "the", "a", "an", "is", "are",
    "what", "how", "why", "when", "who", "does", "do", "this", "that",
    "summarize", "summary", "explain", "describe", "about", "and", "or",
    "pdf", "url", "web", "doc", "document", "file", "also", "ok", "okay"
}

def extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a query, removing stop words."""
    words = re.findall(r"[a-zA-Z]{3,}", query.lower())
    return [w for w in words if w not in STOP_WORDS]


def fetch_user_chunks(chunks_ref, user_email: str, limit: int = 60) -> list[dict]:
    """Fetch up to `limit` processed chunks for this user. Single-index query."""
    results = []
    for doc in (
        chunks_ref
        .where(filter=FieldFilter("user_email", "==", user_email))
        .where(filter=FieldFilter("status", "==", "processed"))
        .limit(limit)
        .stream()
    ):
        data = doc.to_dict()
        results.append({
            "id": doc.id,
            "text": data.get("text", ""),
            "document_name": data.get("document_name", "Unknown"),
            "filename": data.get("filename", ""),
            "page_number": data.get("page_number", 1),
            "source_url": data.get("source_url", ""),
            "chunk_index": data.get("chunk_index", 0),
            "created_at": data.get("created_at"),
            "score": 1.0,
            "doc_type": data.get("doc_type", "pdf")
        })
    return results


def find_best_filename_match(chunks: list[dict], keywords: list[str]) -> Optional[str]:
    """
    Score each unique filename/document_name against query keywords.
    Returns the filename with the highest keyword overlap, or None.
    """
    if not keywords:
        return None

    scores: dict[str, int] = {}
    for chunk in chunks:
        fname = chunk.get("filename", "").lower()
        dname = chunk.get("document_name", "").lower()
        combined = fname + " " + dname
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            key = chunk.get("filename", "")
            scores[key] = max(scores.get(key, 0), score)

    if not scores:
        return None

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 1 else None


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat_with_docs(payload: ChatRequest, user_token: dict = Depends(verify_token)):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    user_query = payload.message.strip()
    if not user_query and not payload.active_context:
        raise HTTPException(status_code=400, detail="Message/Context cannot be empty")

    # ── EARLY EXIT: Skip DB for pure conversational messages ─────────────────
    CONVERSATIONAL_PATTERNS = {
        "hi", "hello", "hey", "how are you", "thanks", "thank you",
        "ok", "okay", "great", "cool", "bye", "goodbye", "who are you",
        "what can you do", "help", "what are you"
    }
    query_lower = user_query.lower().strip()
    is_conversational = (
        not payload.attachment_meta
        and len(user_query) < 60
        and any(query_lower == p or query_lower.startswith(p) for p in CONVERSATIONAL_PATTERNS)
    )
    if is_conversational:
        llm_reply = generate_answer(user_query, [])
        session_id = payload.session_id or str(uuid.uuid4())
        db = firestore.client()
        db.collection("chat_history").add({
            "session_id": session_id, "user_email": user_email,
            "query": user_query, "attachment": None, "reply": llm_reply,
            "sources": [], "timestamp": datetime.now(timezone.utc),
            "title": user_query[:60].strip() or "Chat",
        })
        return {"reply": llm_reply, "session_id": session_id, "context_chunks": []}

    # ── Generate query embedding ──────────────────────────────────────────────
    context_text = payload.active_context or ""
    query_for_search = user_query
    if context_text:
        query_for_search += f"\n\nContext Fragment:\n{context_text}"

    try:
        query_embedding = generate_embedding(query_for_search)
        if not query_embedding or len(query_embedding) == 0:
            raise ValueError("Empty embedding returned.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {str(e)}")

    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    top_chunks = []

    # Resolve active filename from attachment metadata
    active_filename = None
    if payload.attachment_meta:
        active_filename = (
            payload.attachment_meta.get("filename")
            or payload.attachment_meta.get("name")
        )
        if not active_filename or not active_filename.strip():
            active_filename = None

    keywords = extract_keywords(user_query)
    SUMMARIZE_KEYWORDS = {
        "summarize", "summary", "overview", "what is",
        "explain", "describe", "this", "about", "tell me"
    }
    is_summary_query = any(kw in user_query.lower() for kw in SUMMARIZE_KEYWORDS)

    if active_filename:
        # ── PATH A: Explicit document attached ───────────────────────────────
        # Python-side filtering — no composite index needed.
        print(f"[CHAT] PATH A | file='{active_filename}' | summary={is_summary_query}")

        all_user_chunks = fetch_user_chunks(chunks_ref, user_email, limit=60)
        candidate_chunks = [
            c for c in all_user_chunks if c.get("filename") == active_filename
        ]
        candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
        top_chunks = candidate_chunks[:5]
        print(f"[CHAT] PATH A | found {len(top_chunks)}/{len(candidate_chunks)} chunks")

    else:
        # ── PATH B: No explicit attachment — smart auto-search ───────────────
        # Layer 1: Fetch all user chunks once (single-field query, cheap)
        # Layer 2: Keyword-to-filename matching (find the right doc from query text)
        # Layer 3: Vector similarity fallback if no keyword match
        # Layer 4: Most-recent-doc fallback for bare "summarize this"
        print(f"[CHAT] PATH B | keywords={keywords} | summary={is_summary_query}")

        all_user_chunks = fetch_user_chunks(chunks_ref, user_email, limit=60)

        if not all_user_chunks:
            # User has no processed documents at all
            top_chunks = []
        else:
            # Layer 2: keyword → filename match
            matched_filename = find_best_filename_match(all_user_chunks, keywords)

            if matched_filename:
                # Found a document that matches query keywords — use it
                print(f"[CHAT] PATH B | keyword match → '{matched_filename}'")
                candidate_chunks = [
                    c for c in all_user_chunks if c.get("filename") == matched_filename
                ]
                candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
                top_chunks = candidate_chunks[:5]

            elif is_summary_query and not keywords:
                # Layer 4: "summarize this" with no keywords → use most recent doc
                print(f"[CHAT] PATH B | bare summarize → most recent doc")
                # Sort by created_at descending
                sorted_chunks = sorted(
                    all_user_chunks,
                    key=lambda c: c.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True
                )
                # Get the filename of the most recently uploaded chunk
                if sorted_chunks:
                    recent_filename = sorted_chunks[0].get("filename")
                    candidate_chunks = [
                        c for c in all_user_chunks if c.get("filename") == recent_filename
                    ]
                    candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
                    top_chunks = candidate_chunks[:5]

            else:
                # Layer 3: Vector similarity across entire knowledge base
                print(f"[CHAT] PATH B | vector search across all user docs")
                try:
                    for doc in (
                        chunks_ref
                        .where(filter=FieldFilter("user_email", "==", user_email))
                        .where(filter=FieldFilter("status", "==", "processed"))
                        .find_nearest(
                            vector_field="embedding",
                            query_vector=query_embedding,
                            distance_measure=DistanceMeasure.COSINE,
                            limit=5,
                            distance_threshold=0.35,
                            distance_result_field="vector_distance"
                        )
                        .stream()
                    ):
                        data = doc.to_dict()
                        top_chunks.append({
                            "id": doc.id,
                            "text": data.get("text", ""),
                            "document_name": data.get("document_name", "Unknown"),
                            "filename": data.get("filename", ""),
                            "page_number": data.get("page_number", 1),
                            "source_url": data.get("source_url", ""),
                            "score": float(1.0 - data.get("vector_distance", 1.0)),
                            "doc_type": data.get("doc_type", "pdf")
                        })
                except Exception as e:
                    print(f"[CHAT] PATH B vector search failed: {e}, using keyword fallback")
                    # Fallback: return first 5 chunks from any user doc
                    top_chunks = all_user_chunks[:5]

        print(f"[CHAT] PATH B | returning {len(top_chunks)} chunks")

    # ── Generate LLM answer ──────────────────────────────────────────────────
    llm_reply = generate_answer(query_for_search, top_chunks)

    # ── Build safe source citations ───────────────────────────────────────────
    safe_sources = []
    seen_docs = set()
    for c in top_chunks:
        doc_name = c.get("document_name", "Unknown Document")
        if doc_name not in seen_docs:
            seen_docs.add(doc_name)
            entry = {
                "document_name": doc_name,
                "doc_type": c.get("doc_type", "pdf"),
            }
            # Only expose source_url for web/scraped content — not for local PDF paths
            if c.get("source_url") and c.get("doc_type") == "web":
                entry["source_url"] = c.get("source_url")
            safe_sources.append(entry)

    # ── Persist to Firestore chat_history ────────────────────────────────────
    session_id = payload.session_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.collection("chat_history").add({
        "session_id": session_id,
        "user_email": user_email,
        "query": user_query,
        "attachment": payload.attachment_meta,
        "reply": llm_reply,
        "sources": safe_sources,
        "timestamp": now,
        "title": user_query[:60].strip() or "New Chat",
    })

    return {
        "reply": llm_reply,
        "session_id": session_id,
        "context_chunks": safe_sources
    }
