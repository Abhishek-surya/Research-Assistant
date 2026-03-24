from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
from api.deps import verify_token
from services.chunker import chunk_and_save
from services.html_cleaner import clean_html
import pdfplumber
import shutil
import tempfile
import os

router = APIRouter()

@router.post("/upload")
async def upload_document(
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

    # ── PDF ──────────────────────────────────────────────────────────────
    if "pdf" in mime or filename.lower().endswith(".pdf"):
        doc_type = "pdf"
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        try:
            os.close(fd)
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(document.file, buffer)
                
            with pdfplumber.open(temp_path) as pdf:
                pages_text: list[str] = []
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages_text.append(f"--- Page {i+1} ---\n{text}")
                extracted_text = "\n\n".join(pages_text)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to extract PDF text: {str(e)}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # ── HTML & Text ─────────────────────────────────────────────────────
    else:
        contents = await document.read()
        
        if "html" in mime or filename.lower().endswith((".html", ".htm")):
            doc_type = "html"
            raw_html = contents.decode("utf-8", errors="replace")
            extracted_text = clean_html(raw_html)

        elif "text" in mime or filename.lower().endswith(".txt"):
            doc_type = "text"
            extracted_text = contents.decode("utf-8", errors="replace")

        else:
            try:
                raw = contents.decode("utf-8", errors="replace")
                if raw.lstrip().startswith("<"):
                    doc_type = "html"
                    extracted_text = clean_html(raw)
                else:
                    extracted_text = raw
            except Exception:
                raise HTTPException(status_code=415, detail="Unsupported file type.")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the document.")

    # ── Chunk & persist to Firestore ─────────────────────────────────────
    chunk_count = chunk_and_save(
        text=extracted_text,
        document_name=filename,
        user_email=user_email,
        filename=filename,
        source_url=f"local://{user_email}/{filename}",
        doc_type=doc_type
    )

    return {
        "message": "Document processed and chunked successfully",
        "filename": filename,
        "text": extracted_text,
        "char_count": len(extracted_text),
        "chunk_count": chunk_count
    }
