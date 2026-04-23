from fastapi import APIRouter, Depends, HTTPException
from api.deps import verify_token
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import os
from urllib.parse import unquote

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


import time

_processing_cache = {}
CACHE_TTL = 30  # seconds — check embedding status at most once per 30s to save quota

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

    # Sanitize: Handle URL-encoded filenames (e.g. spaces)
    filename = unquote(filename)

    # 1. Delete the local file if it exists
    filepath = os.path.join(DATA_DIR, user_email, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    else:
        # On Render, local storage is ephemeral. Chunks usually outlive files.
        print(f"[DELETE] Warning: Local file {filename} not found, proceeding with Firestore cleanup.")

    # 2. Cascade delete all matching document_chunks from Firestore
    db = firestore.client()
    chunks_ref = db.collection("document_chunks")

    deleted_count = 0
    batch = db.batch()

    # Targeted query: filter by BOTH user_email AND filename — no full-collection scan.
    # This requires the composite index (user_email, filename) to exist in Firestore.
    print(f"[DELETE] Targeted chunk query: user={user_email}, filename={filename}")
    targeted_chunks = (
        chunks_ref
        .where(filter=FieldFilter("user_email", "==", user_email))
        .where(filter=FieldFilter("filename", "==", filename))
        .stream()
    )
    for doc in targeted_chunks:
        batch.delete(doc.reference)
        deleted_count += 1
        if deleted_count % 400 == 0:
            batch.commit()
            batch = db.batch()

    # Also clean up any old chunks stored under document_name instead of filename
    name_chunks = (
        chunks_ref
        .where(filter=FieldFilter("user_email", "==", user_email))
        .where(filter=FieldFilter("document_name", "==", filename))
        .stream()
    )
    for doc in name_chunks:
        data = doc.to_dict()
        if data.get("filename", "") != filename:  # Avoid double-deleting
            batch.delete(doc.reference)
            deleted_count += 1
            if deleted_count % 400 == 0:
                batch.commit()
                batch = db.batch()

    if deleted_count % 400 != 0 or deleted_count == 0:
        batch.commit()

    print(f"[DELETE] Total deleted: {deleted_count} chunks")

    return {
        "message": f"Document '{filename}' and {deleted_count} chunks deleted successfully",
        "filename": filename,
        "chunks_deleted": deleted_count
    }

