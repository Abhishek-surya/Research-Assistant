"""
Background embedding processor: fetches unprocessed document chunks
from Firestore and generates vector embeddings using HuggingFace.

Optimizations:
- BATCH_SIZE = 150       (larger batches per HuggingFace call)
- MAX_TOTAL_PER_RUN = 1000 (no artificial pause limit)
- ThreadPoolExecutor     (parallel HuggingFace API calls per batch group)
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.vector import Vector
from services.embedder import generate_embeddings_batch

logger = logging.getLogger(__name__)

BATCH_SIZE = 150       # Chunks per single HuggingFace API call
MAX_TOTAL_PER_RUN = 1000  # Process up to 1000 chunks per trigger (one large PDF easily)
MAX_PARALLEL_CALLS = 3    # Up to 3 HuggingFace calls in parallel


def _embed_and_save_batch(batch_docs: list, db) -> tuple[int, int]:
    """
    Embed one batch of docs and persist results to Firestore.
    Returns (success_count, fail_count).
    """
    texts = []
    valid_docs = []

    for doc in batch_docs:
        data = doc.to_dict()
        text = data.get("text", "")
        if text.strip():
            texts.append(text)
            valid_docs.append(doc)
        else:
            # Skip empty, mark as skipped
            try:
                doc.reference.update({"status": "skipped", "error": "Empty text"})
            except Exception:
                pass

    if not texts:
        return 0, 0

    success = 0
    fail = 0

    try:
        embeddings = generate_embeddings_batch(texts)

        for doc, embedding in zip(valid_docs, embeddings):
            try:
                doc.reference.update({
                    "embedding": Vector(embedding),
                    "status": "processed",
                    "embedded_at": datetime.now(timezone.utc),
                    "error": firestore.DELETE_FIELD,
                })
                success += 1
            except Exception as e:
                logger.warning(f"[Scheduler] Firestore write failed: {e}")
                fail += 1

    except Exception as e:
        logger.warning(f"[Scheduler] Batch embedding API call failed: {e}")
        # Mark all docs in this batch as failed so they retry next time
        for doc in valid_docs:
            try:
                doc.reference.update({"status": "embedding_failed", "error": str(e)})
            except Exception:
                pass
        fail += len(valid_docs)

    return success, fail


def process_pending_chunks():
    """
    Core job: embed ALL unprocessed chunks in parallel batches.
    Triggered immediately after every upload or scrape event.
    """
    db = firestore.client()
    collection = db.collection("document_chunks")

    total_success = 0
    total_fail = 0
    total_seen = 0

    logger.info("[Scheduler] Starting embedding run...")

    while total_seen < MAX_TOTAL_PER_RUN:
        # Fetch the next window of pending chunks
        pending = []
        for status in ("new", "embedding_failed"):
            docs = (
                collection
                .where(filter=FieldFilter("status", "==", status))
                .limit(BATCH_SIZE * MAX_PARALLEL_CALLS)  # Fetch enough for all parallel calls
                .stream()
            )
            for doc in docs:
                pending.append(doc)
            if len(pending) >= BATCH_SIZE * MAX_PARALLEL_CALLS:
                break

        if not pending:
            logger.info(f"[Scheduler] All done. Embedded {total_success} chunks, {total_fail} failed.")
            break

        total_seen += len(pending)
        logger.info(f"[Scheduler] Processing {len(pending)} chunks in parallel batches...")

        # Split into sub-batches for parallel processing
        sub_batches = [
            pending[i:i + BATCH_SIZE]
            for i in range(0, len(pending), BATCH_SIZE)
        ]

        # Run sub-batches in parallel using a thread pool
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as executor:
            futures = {
                executor.submit(_embed_and_save_batch, batch, db): batch
                for batch in sub_batches
            }
            for future in as_completed(futures):
                try:
                    s, f = future.result()
                    total_success += s
                    total_fail += f
                except Exception as e:
                    logger.error(f"[Scheduler] Parallel batch crashed: {e}")
                    total_fail += BATCH_SIZE  # Pessimistic count

        # If we got fewer docs than a full window, we've processed everything
        if len(pending) < BATCH_SIZE * MAX_PARALLEL_CALLS:
            logger.info(f"[Scheduler] Completed. Total embedded: {total_success}, failed: {total_fail}")
            break

    return {
        "processed": total_seen,
        "success": total_success,
        "failed": total_fail
    }
