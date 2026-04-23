"""
Background scheduler: every 2 minutes, fetches up to 50 document chunks
with status='new' or status='embedding_failed' from Firestore, generates
vector embeddings using Gemini, and updates their status to 'processed'.
"""
import logging
from datetime import datetime, timezone
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.vector import Vector
from services.embedder import generate_embedding, generate_embeddings_batch

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def process_pending_chunks():
    """
    Core job function: embed unprocessed chunks per run until exhaustion.
    """
    db = firestore.client()
    collection = db.collection("document_chunks")

    total_processed = 0
    total_success = 0
    total_failed = 0

    MAX_TOTAL_PER_RUN = 200

    while True:
        if total_processed >= MAX_TOTAL_PER_RUN:
            logger.info(f"[Scheduler] Reached MAX_TOTAL_PER_RUN ({MAX_TOTAL_PER_RUN}). Pausing.")
            break
            
        pending = []
        for status in ("new", "embedding_failed"):
            docs = (
                collection
                .where(filter=FieldFilter("status", "==", status))
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
            break

        logger.info(f"[Scheduler] Found {len(pending)} pending chunk(s). Embedding now...")

        valid_docs = []
        texts_to_embed = []

        for doc in pending:
            data = doc.to_dict()
            text = data.get("text", "")

            if not text.strip():
                doc.reference.update({"status": "skipped", "error": "Empty text"})
                continue
                
            valid_docs.append(doc)
            texts_to_embed.append(text)

        if texts_to_embed:
            batch_failed = False
            try:
                embeddings = generate_embeddings_batch(texts_to_embed)
                
                for doc, embedding in zip(valid_docs, embeddings):
                    try:
                        doc.reference.update({
                            "embedding": Vector(embedding),
                            "status": "processed",
                            "embedded_at": datetime.now(timezone.utc),
                            "error": firestore.DELETE_FIELD, 
                        })
                        total_success += 1
                    except Exception as e:
                        logger.warning(f"[Scheduler] Firestore update failed for a doc: {e}")
                        total_failed += 1
            except Exception as e:
                logger.warning(f"[Scheduler] Batch embedding failed: {e}")
                for doc in valid_docs:
                    try:
                        doc.reference.update({
                            "status": "embedding_failed",
                            "error": str(e),
                        })
                    except Exception:
                        pass
                    total_failed += 1
                batch_failed = True

            total_processed += len(pending)

            # Do not infinitely loop if we are hitting hard quota errors
            if batch_failed:
                break

    return {
        "processed": total_processed,
        "success": total_success,
        "failed": total_failed
    }
