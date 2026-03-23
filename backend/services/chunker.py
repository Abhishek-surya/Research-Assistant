"""
Shared document chunking service.
Splits text using LangChain's RecursiveCharacterTextSplitter and
saves each chunk to Firestore with status='new'.

Embedding is handled separately by the background scheduler
(services/embedding_scheduler.py) every 2 minutes.
"""
import re
from datetime import datetime, timezone
from langchain_text_splitters import RecursiveCharacterTextSplitter
from firebase_admin import firestore

# Chunking parameters
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def _clean_text(text: str) -> str:
    """
    Pre-process text extracted from PDFs to fix common garbling issues:
    1. Missing spaces before bullet characters (•, ·, etc.)
    2. Words that got concatenated (e.g. 'fromyour' → 'from your')
    3. Multiple spaces/newlines collapsed to single space
    """
    # Ensure space before common bullet/list characters
    text = re.sub(r'(?<=[^\s])([•·▸▪▸‣⁃])', r' \1', text)
    # Ensure space after bullet characters
    text = re.sub(r'([•·▸▪▸‣⁃])(?=[^\s])', r'\1 ', text)
    # Break apart commonly glued words: lowercase followed immediately by uppercase letter (CamelCase boundary)
    # e.g. 'fromYour' → 'from Your' but NOT 'PDF' or 'LaTeX'
    text = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', text)
    # Fix missing space after period when next word starts (e.g. 'end.Start' → 'end. Start')
    text = re.sub(r"\.([A-Z])", r". \1", text)
    # Collapse 3+ newlines into paragraph break
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip leading/trailing whitespace
    return text.strip()


def _infer_page_number(text: str, chunk_text: str) -> int:
    """
    Infer page number by locating the nearest '--- Page N ---' marker
    before the chunk's start position.
    """
    try:
        chunk_pos = text.find(chunk_text[:80])
        markers = [(m.start(), int(m.group(1)))
                   for m in re.finditer(r'--- Page (\d+) ---', text[:chunk_pos])]
        if markers:
            return markers[-1][1]
    except Exception:
        pass
    return 1


def chunk_and_save(
    text: str,
    document_name: str,
    user_email: str,
    filename: str = "",
    source_url: str = "",
    doc_type: str = "pdf"
) -> int:
    """
    Split text into chunks and persist each to Firestore with status='new'.
    Embedding is picked up by the background scheduler — upload returns instantly.
    Returns the number of chunks created.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text)

    db = firestore.client()
    collection = db.collection("document_chunks")
    created_at = datetime.now(timezone.utc)

    for idx, chunk_text in enumerate(chunks):
        page_number = _infer_page_number(text, chunk_text)

        doc_data = {
            "text": chunk_text,
            "chunk_index": idx,
            "page_number": page_number,
            "document_name": document_name,
            "filename": filename or document_name,
            "source_url": source_url,
            "user_email": user_email,
            "doc_type": doc_type,
            "created_at": created_at,
            "status": "new",              # Scheduler will embed and flip to "processed"
            "char_count": len(chunk_text),
        }
        collection.add(doc_data)

    print(f"[Chunker] Saved {len(chunks)} chunks for '{document_name}' → pending embedding")
    return len(chunks)
