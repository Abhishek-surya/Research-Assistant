"""
Background scheduler: every 2 minutes, fetches up to 50 document chunks
with status='new' or status='embedding_failed' from Firestore, generates
vector embeddings using Gemini, and updates their status to 'processed'.
"""
import logging
from datetime import datetime, timezone
from firebase_admin import firestore
from services.embedder import generate_embedding, generate_embeddings_batch

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def process_pending_chunks():
    """
    Core job function: embed up to BATCH_SIZE unprocessed chunks per run.
    Called by APScheduler every 2 minutes.
    """
    db = firestore.client()
    collection = db.collection("document_chunks")

    # Fetch chunks that still need embedding — status "new" or "embedding_failed"
    pending = []
    for status in ("new", "embedding_failed"):
        docs = (
            collection
            .where("status", "==", status)
            .limit(BATCH_SIZE)
            .stream()
        )
        for doc in docs:
            pending.append(doc)
            if len(pending) >= BATCH_SIZE:
                break
        if len(pending) >= BATCH_SIZE:
            break

    if not pending:
        logger.debug("[Scheduler] No pending chunks — nothing to embed.")
        return

    logger.info(f"[Scheduler] Found {len(pending)} pending chunk(s). Embedding now...")

    success = 0
    failed = 0

    valid_docs = []
    texts_to_embed = []

    for doc in pending:
        data = doc.to_dict()
        text = data.get("text", "")
        doc_name = data.get("document_name", "?")

        if not text.strip():
            doc.reference.update({"status": "skipped", "error": "Empty text"})
            continue
            
        valid_docs.append(doc)
        texts_to_embed.append(text)

    if texts_to_embed:
        try:
            embeddings = generate_embeddings_batch(texts_to_embed)
            
            for doc, embedding in zip(valid_docs, embeddings):
                try:
                    doc.reference.update({
                        "embedding": embedding,
                        "status": "processed",
                        "embedded_at": datetime.now(timezone.utc),
                        "error": firestore.DELETE_FIELD,   # clear any previous error
                    })
                    success += 1
                except Exception as e:
                    logger.warning(f"[Scheduler] Firestore update failed for a doc: {e}")
                    failed += 1
        except Exception as e:
            logger.warning(f"[Scheduler] Batch embedding failed: {e}")
            for doc in valid_docs:
                try:
                    doc.reference.update({
                        "status": "embedding_failed",
                        "error": str(e),
                    })
                except Exception as inner_e:
                    pass
                failed += 1

    logger.info(
        f"[Scheduler] Batch complete — "
        f"{success} embedded ✅ | {failed} failed ⚠️"
    )
