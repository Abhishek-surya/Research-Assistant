from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from api.deps import verify_token
from services.chunker import chunk_and_save
from services.embedding_scheduler import process_pending_chunks
from services.html_cleaner import clean_html
from bs4 import BeautifulSoup
import requests
import os
import re
import io
import pdfplumber
from urllib.parse import urlparse

router = APIRouter()

class ScrapeRequest(BaseModel):
    url: str

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

def sanitize_filename(url: str) -> str:
    """Convert a URL into a safe filename."""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r'[^\w\-_.]', '_', name)
    name = name.strip('_')[:100]  # limit length
    return name + ".html"

@router.post("/scrape")
async def scrape_url(
    payload: ScrapeRequest, 
    background_tasks: BackgroundTasks,
    user_token: dict = Depends(verify_token)
):
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    user_email = user_token.get("email")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in token")

    # Fetch the page
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RAG-Bot/1.0)"}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")

    # Check if the response is actually a PDF
    content_type = response.headers.get("Content-Type", "").lower()
    is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")

    title = urlparse(url).netloc
    
    if is_pdf:
        # Extract text from PDF
        try:
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                pages_text = []
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(f"--- Page {i+1} ---\n{page_text}")
                text = "\n\n".join(pages_text)
                title = f"PDF: {urlparse(url).path.split('/')[-1] or urlparse(url).netloc}"
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to scrape PDF: {str(e)}")
        doc_type = "pdf"
    else:
        # Parse and clean HTML using BeautifulSoup
        soup = BeautifulSoup(response.text, "lxml")
        
        # Remove scripts, styles, nav, footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        
        # Extract page title separately, then clean text via shared cleaner
        title = soup.title.string.strip() if soup.title else urlparse(url).netloc
        text = clean_html(response.text)
        doc_type = "web"
    
    # Save as an .html file locally in data/{email}/ folder
    user_dir = os.path.join(DATA_DIR, user_email)
    os.makedirs(user_dir, exist_ok=True)
    
    filename = sanitize_filename(url)
    filepath = os.path.join(user_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"<!-- Scraped from: {url} -->\n")
        f.write(f"<!-- Title: {title} -->\n\n")
        f.write(text)

    # --- Chunk & save to Firestore ---
    chunk_count = chunk_and_save(
        text=text,
        document_name=title,
        user_email=user_email,
        filename=filename,
        source_url=url,
        doc_type=doc_type
    )

    background_tasks.add_task(process_pending_chunks)

    return {
        "message": "Page scraped successfully",
        "url": url,
        "title": title,
        "filename": filename,
        "text": text,
        "char_count": len(text),
        "chunk_count": chunk_count
    }
