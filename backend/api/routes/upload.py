from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, BackgroundTasks
from api.deps import verify_token
from services.chunker import chunk_and_save
from services.embedding_scheduler import process_pending_chunks
from services.html_cleaner import clean_html
import pdfplumber
import shutil
import tempfile
import os

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    document: UploadFile = File(...),
    user_token: dict = Depends(verify_token)
):
    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    extracted_text = ""
    mime = document.content_type or ""
    filename = document.filename or "document"
    doc_type = "text"

    # ── PDF ───────────────────────────────────────────────────────────────────
    if "pdf" in mime or filename.lower().endswith(".pdf"):
        doc_type = "pdf"
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        try:
            os.close(fd)
            print(f"[UPLOAD] Extracting PDF: {filename}")
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(document.file, buffer)

            with pdfplumber.open(temp_path) as pdf:
                pages_text: list[str] = []
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages_text.append(f"--- Page {i+1} ---\n{text}")
                extracted_text = "\n\n".join(pages_text)

            print(f"[UPLOAD] PDF extracted: {len(extracted_text)} chars from {len(pages_text)} pages")
        except Exception as e:
            print(f"[UPLOAD] ERROR extracting PDF '{filename}': {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=422,
                detail=f"PDF extraction failed ({type(e).__name__}): {str(e)}"
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # ── HTML & Text ───────────────────────────────────────────────────────────
    else:
        try:
            contents = await document.read()

            if "html" in mime or filename.lower().endswith((".html", ".htm")):
                doc_type = "html"
                raw_html = contents.decode("utf-8", errors="replace")
                extracted_text = clean_html(raw_html)

            elif "text" in mime or filename.lower().endswith(".txt"):
                doc_type = "text"
                extracted_text = contents.decode("utf-8", errors="replace")

            else:
                raw = contents.decode("utf-8", errors="replace")
                if raw.lstrip().startswith("<"):
                    doc_type = "html"
                    extracted_text = clean_html(raw)
                else:
                    extracted_text = raw
        except Exception as e:
            print(f"[UPLOAD] ERROR reading file '{filename}': {type(e).__name__}: {e}")
            raise HTTPException(status_code=415, detail=f"Could not read file ({type(e).__name__}): {str(e)}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the document.")

    # ── Hard-delete stale local file before re-writing ────────────────────────
    # This ensures re-uploads with the same filename are always treated as fresh.
    user_dir = os.path.join(DATA_DIR, user_email)
    os.makedirs(user_dir, exist_ok=True)
    filepath = os.path.join(user_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        print(f"[UPLOAD] Removed stale local file for re-upload: {filepath}")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"<!-- Title: {filename} -->\n\n")
        f.write(extracted_text)

    # ── Wipe old Firestore chunks before re-ingestion ─────────────────────────
    from firebase_admin import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    docs = chunks_ref.where(
        filter=FieldFilter("user_email", "==", user_email)
    ).where(
        filter=FieldFilter("filename", "==", filename)
    ).stream()

    batch = db.batch()
    deleted_count = 0
    for doc in docs:
        batch.delete(doc.reference)
        deleted_count += 1
        if deleted_count % 400 == 0:
            batch.commit()
            batch = db.batch()
    if deleted_count > 0:
        batch.commit()
        print(f"[UPLOAD] Wiped {deleted_count} existing chunks for '{filename}' before re-ingestion")

    # ── Chunk & persist new chunks to Firestore ───────────────────────────────
    try:
        chunk_count = chunk_and_save(
            text=extracted_text,
            document_name=filename,
            user_email=user_email,
            filename=filename,
            source_url=f"local://{user_email}/{filename}",
            doc_type=doc_type
        )
        print(f"[UPLOAD] Created {chunk_count} new chunks for '{filename}'")
    except Exception as e:
        print(f"[UPLOAD] ERROR creating chunks for '{filename}': {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chunking failed ({type(e).__name__}): {str(e)}"
        )

    background_tasks.add_task(process_pending_chunks)

    return {
        "message": "Document processed and chunked successfully",
        "filename": filename,
        "char_count": len(extracted_text),
        "chunk_count": chunk_count
    }
