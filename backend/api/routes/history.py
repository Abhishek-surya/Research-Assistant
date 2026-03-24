from fastapi import APIRouter, Depends, HTTPException
from api.deps import verify_token
from firebase_admin import firestore

router = APIRouter()


@router.get("/chats")
async def get_chat_sessions(user_token: dict = Depends(verify_token)):
    """
    Return the list of unique chat sessions for the user,
    ordered by most recent first. Each session has:
      - session_id
      - title  (first message's text, trimmed)
      - timestamp (of the most recent message in that session)
    """
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    db = firestore.client()
    docs = (
        db.collection("chat_history")
        .where("user_email", "==", user_email)
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .stream()
    )

    # Deduplicate: keep only the first (latest) doc per session_id
    seen: set[str] = set()
    sessions = []
    for doc in docs:
        data = doc.to_dict()
        sid = data.get("session_id")
        if sid and sid not in seen:
            seen.add(sid)
            ts = data.get("timestamp")
            sessions.append({
                "session_id": sid,
                "title": data.get("title", "Untitled Chat"),
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            })

    return {"sessions": sessions}


@router.get("/chats/{session_id}")
async def get_session_messages(session_id: str, user_token: dict = Depends(verify_token)):
    """
    Return all Q&A turns for a given session_id, ordered oldest first.
    """
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    db = firestore.client()
    docs = (
        db.collection("chat_history")
        .where("user_email", "==", user_email)
        .where("session_id", "==", session_id)
        .order_by("timestamp", direction=firestore.Query.ASCENDING)
        .stream()
    )

    messages = []
    for doc in docs:
        data = doc.to_dict()
        ts = data.get("timestamp")
        messages.append({
            "query": data.get("query", ""),
            "reply": data.get("reply", ""),
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        })

    return {"messages": messages}
