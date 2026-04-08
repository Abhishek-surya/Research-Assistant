from fastapi import APIRouter, HTTPException, Header
import os
import logging
from services.embedding_scheduler import process_pending_chunks

router = APIRouter(tags=["Jobs"])
logger = logging.getLogger(__name__)

# Simple security: You can set a CRON_SECRET in your environment variables
# If not set, it will allow the request but will log a warning
CRON_SECRET = os.environ.get("CRON_SECRET", None)

@router.post("/jobs/process-embeddings")
async def trigger_embedding_job(x_job_token: str = Header(None)):
    """
    Endpoint to trigger the embedding process manually or via external cron.
    """
    if CRON_SECRET and x_job_token != CRON_SECRET:
        logger.warning("Unauthorized attempt to trigger embedding job.")
        raise HTTPException(status_code=403, detail="Unauthorized")

    try:
        logger.info("External trigger received for embedding job.")
        result = process_pending_chunks()
        return {
            "status": "success",
            "message": "Embedding job completed",
            "data": result
        }
    except Exception as e:
        logger.exception("Error during embedding job execution")
        raise HTTPException(status_code=500, detail=str(e))
