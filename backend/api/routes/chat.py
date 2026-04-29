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

    q_lower_full = user_query.lower().strip()

    if active_filename:
        # ── PATH A: Explicit document attached ─────────────────────────────
        print(f"[CHAT] PATH A | file='{active_filename}' | summary={is_summary_query}")
        all_user_chunks = fetch_user_chunks(chunks_ref, user_email, limit=60)
        candidate_chunks = [
            c for c in all_user_chunks if c.get("filename") == active_filename
        ]
        candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
        top_chunks = candidate_chunks[:5]
        print(f"[CHAT] PATH A | found {len(top_chunks)}/{len(candidate_chunks)} chunks")

    else:
        # ── PATH B: No explicit attachment — smart auto-search ──────────────
        print(f"[CHAT] PATH B | keywords={keywords} | summary={is_summary_query}")
        all_user_chunks = fetch_user_chunks(chunks_ref, user_email, limit=60)

        if not all_user_chunks:
            top_chunks = []
        else:
            matched_filename = find_best_filename_match(all_user_chunks, keywords)

            if matched_filename:
                print(f"[CHAT] PATH B | keyword match → '{matched_filename}'")
                candidate_chunks = [
                    c for c in all_user_chunks if c.get("filename") == matched_filename
                ]
                candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
                top_chunks = candidate_chunks[:5]

            elif is_summary_query and not keywords:
                print(f"[CHAT] PATH B | bare summarize → most recent doc")
                sorted_chunks = sorted(
                    all_user_chunks,
                    key=lambda c: c.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True
                )
                if sorted_chunks:
                    recent_filename = sorted_chunks[0].get("filename")
                    candidate_chunks = [
                        c for c in all_user_chunks if c.get("filename") == recent_filename
                    ]
                    candidate_chunks.sort(key=lambda c: c.get("chunk_index", 0))
                    top_chunks = candidate_chunks[:5]

            else:
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
                            distance_threshold=0.18,  # score >= 0.82
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
                    print(f"[CHAT] PATH B vector search failed: {e}")
                    top_chunks = []

        print(f"[CHAT] PATH B | returning {len(top_chunks)} chunks")

    # ── Quality gate: score >= 0.82 required for verified sources ─────────────
    SCORE_THRESHOLD = 0.82
    quality_chunks = [c for c in top_chunks if c.get("score", 0.0) >= SCORE_THRESHOLD]
    print(f"[CHAT] quality_chunks={len(quality_chunks)}/{len(top_chunks)} above {SCORE_THRESHOLD}")

    # ── Search Gatekeeper ─────────────────────────────────────────────────────
    INTERNAL_KNOWLEDGE_PATTERNS = {
        "who are you", "what are you", "what can you do", "tell me a joke",
        "how are you", "what is your name", "help me", "what do you do",
        "introduce yourself", "tell me about yourself"
    }
    word_count = len(user_query.split())
    is_internal_knowledge = any(
        q_lower_full.startswith(p) or q_lower_full == p
        for p in INTERNAL_KNOWLEDGE_PATTERNS
    )

    # Universal Search Trigger with 3-word Safety Gate
    needs_search = (
        not quality_chunks
        and word_count >= 3
        and not is_internal_knowledge
    )
    print(f"[CHAT] needs_search={needs_search} | internal={is_internal_knowledge}")

    # ── Generate LLM answer ───────────────────────────────────────────────────
    llm_reply = generate_answer(query_for_search, quality_chunks, use_search=needs_search)

    # ── Silent Fallback to Search ─────────────────────────────────────────────
    NO_CONTEXT_PHRASES = [
        "does not contain information", "not in the context", "context does not",
        "provided context does not"
    ]
    
    # If we tried to use documents but the LLM found them insufficient, 
    # try Google Search silently (if query qualifies).
    if not needs_search and word_count >= 3 and not is_internal_knowledge:
        if any(p in llm_reply.lower() for p in NO_CONTEXT_PHRASES):
            print("[CHAT] Document context rejected by LLM. Silent fallback to Google Search.")
            needs_search = True
            # Re-generate with search enabled
            llm_reply = generate_answer(query_for_search, [], use_search=True)

    # ── Build safe source citations ───────────────────────────────────────────
    if needs_search:
        # WEB SEARCH MODE: source is always and only Google Search.
        # Never allow PDF names to leak into a web-based answer.
        safe_sources = [{"is_google": True, "document_name": "Google Search"}]
        print(f"[CHAT] Sources: Google Search (web mode)")
    else:
        # DOCUMENT MODE: build sources from quality_chunks only.
        BROAD_OVERVIEW_WORDS = {
            "summarize", "summary", "brief", "overview",
            "explain", "describe", "tell me about"
        }
        q_lower = user_query.lower()
        is_summary = (
            any(kw in q_lower for kw in BROAD_OVERVIEW_WORDS)
            and len(user_query.split()) >= 3
        )

        safe_sources: list = []
        seen_docs: set = set()
        for c in quality_chunks:
            doc_name = c.get("document_name", "Unknown Document")
            if doc_name in seen_docs:
                continue
            seen_docs.add(doc_name)
            entry = {
                "document_name": doc_name,
                "doc_type": c.get("doc_type", "pdf"),
                "page_number": c.get("page_number"),
                "is_summary": is_summary,
            }
            if c.get("source_url") and c.get("doc_type") == "web":
                entry["source_url"] = c.get("source_url")
            safe_sources.append(entry)

        # Safety-net: if LLM STILL says context not found (shouldn't happen with fallback, but just in case)
        if any(p in llm_reply.lower() for p in NO_CONTEXT_PHRASES):
            print(f"[CHAT] Safety-net: clearing sources (LLM stated no context match)")
            safe_sources = []
            # Strip the LLM-generated sources text if it rejected it
            llm_reply = re.sub(r"\n+---\n+\*\*Sources:\*\*.*$", "", llm_reply, flags=re.IGNORECASE).strip()

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
