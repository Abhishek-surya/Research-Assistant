from fastapi import APIRouter, Depends, HTTPException
from api.deps import verify_token
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import os

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


import time

_processing_cache = {}
CACHE_TTL = 5  # seconds (Lowered for snappier UI refreshes)

@router.get("/documents")
async def list_documents(user_token: dict = Depends(verify_token)):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    user_dir = os.path.join(DATA_DIR, user_email)

    if not os.path.exists(user_dir):
        return {"documents": []}

    # Identify files that are still processing (Cache to prevent read quota burn)
    now = time.time()
    processing_filenames = set()
    failed_filenames = set()
    
    if user_email in _processing_cache and (now - _processing_cache[user_email]["time"] < CACHE_TTL):
        processing_filenames = _processing_cache[user_email].get("processing", set())
        failed_filenames = _processing_cache[user_email].get("failed", set())
    else:
        db = firestore.client()
        chunks_ref = db.collection("document_chunks")
        
        # Indexed query to find chunks still processing
        docs = chunks_ref.where(filter=FieldFilter("user_email", "==", user_email)).where(filter=FieldFilter("status", "==", "new")).stream()
        for doc in docs:
            data = doc.to_dict()
            fn = data.get("filename") or data.get("document_name")
            if fn:
                processing_filenames.add(fn)
                
        # Indexed query to find chunks that failed embedding
        docs_failed = chunks_ref.where(filter=FieldFilter("user_email", "==", user_email)).where(filter=FieldFilter("status", "==", "embedding_failed")).stream()
        for doc in docs_failed:
            data = doc.to_dict()
            fn = data.get("filename") or data.get("document_name")
            if fn:
                failed_filenames.add(fn)
        
        _processing_cache[user_email] = {
            "time": now,
            "processing": processing_filenames,
            "failed": failed_filenames
        }

    documents = []
    for filename in os.listdir(user_dir):
        filepath = os.path.join(user_dir, filename)
        stat = os.stat(filepath)

        source_url = ""
        doc_title = filename
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                first_lines = [f.readline(), f.readline()]
                for line in first_lines:
                    if "Scraped from:" in line:
                        source_url = line.replace("<!-- Scraped from:", "").replace("-->", "").strip()
                    elif "Title:" in line:
                        doc_title = line.replace("<!-- Title:", "").replace("-->", "").strip()
        except Exception:
            pass

        if filename.endswith(".html"):
            doc_type = "web"
        elif filename.endswith(".pdf"):
            doc_type = "pdf"
        else:
            doc_type = "text"

        status = "ready"
        if filename in failed_filenames:
            status = "error"
        elif filename in processing_filenames:
            status = "processing"

        documents.append({
            "name": doc_title or filename,
            "filename": filename,
            "type": doc_type,
            "source_url": source_url,
            "size": stat.st_size,
            "created": stat.st_mtime,
            "status": status
        })

    documents.sort(key=lambda x: x["created"], reverse=True)
    return {"documents": documents}


@router.delete("/documents/{filename}")
async def delete_document(filename: str, user_token: dict = Depends(verify_token)):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    # Invalidate the processing status cache for this user
    _processing_cache.pop(user_email, None)

    # 1. Delete the local file
    filepath = os.path.join(DATA_DIR, user_email, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Document '{filename}' not found")

    os.remove(filepath)

    # 2. Cascade delete all matching document_chunks from Firestore
    db = firestore.client()
    chunks_ref = db.collection("document_chunks")

    deleted_count = 0
    batch = db.batch()
    
    # Use single-field query (no composite index needed) then filter in Python
    # This avoids composite index build-time race conditions entirely
    print(f"[DELETE] Searching chunks: user={user_email}, filename={filename}")
    all_user_chunks = chunks_ref.where(filter=FieldFilter("user_email", "==", user_email)).stream()
    for doc in all_user_chunks:
        data = doc.to_dict()
        stored_filename = data.get("filename", "")
        stored_doc_name = data.get("document_name", "")
        # Match the dedicated filename field OR document_name (fallback for old chunks without filename)
        if stored_filename == filename or stored_doc_name == filename:
            batch.delete(doc.reference)
            deleted_count += 1
            print(f"  ⏳ Queued chunk {doc.id[:20]} for deletion")
            
            # Firestore limit: 499 operations per batch, flush when reaching 400 for safety
            if deleted_count % 400 == 0:
                batch.commit()
                batch = db.batch()

    # Commit any remaining deletes in the batch
    if deleted_count % 400 != 0:
        batch.commit()

    print(f"[DELETE] Total deleted: {deleted_count} chunks")

    return {
        "message": f"Document '{filename}' and {deleted_count} chunks deleted successfully",
        "filename": filename,
        "chunks_deleted": deleted_count
    }
