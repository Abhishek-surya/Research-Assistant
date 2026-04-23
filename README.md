# AI Research Assistant (RAG Optimized)

A high-performance AI Research Assistant built with a specialized RAG (Retrieval-Augmented Generation) pipeline, optimized for memory-constrained environments (like Render Free Tier) and minimized database costs.

## 🚀 Key Features

- **Hybrid Embedding Engine**: Powered by HuggingFace Serverless Inference (`all-MiniLM-L6-v2`) for zero-RAM, 384-dimensional vector embeddings.
- **Smart Vector Search**: Uses Firestore Vector Search with custom compound indexes for lightning-fast, targeted context retrieval.
- **Quota Optimized**: 
  - Reduced Firestore Reads by ~75% through intelligent context caching and targeted queries.
  - Conservative background polling only when documents are processing.
- **Clean UI/UX**: Premium dark-mode interface with real-time markdown rendering and source citation debug tools.
- **Multi-Source Ingestion**: Support for PDF uploads and live high-fidelity Web Scraping.

## 🛠 Tech Stack

- **Frontend**: React (Vite), Lucide Icons, React Markdown.
- **Backend**: FastAPI (Python), APScheduler for background ingestion.
- **Database**: Firebase Firestore (NoSQL + Vector Indexing).
- **AI Models**: 
  - **Generation**: Google Gemini 1.5 Flash.
  - **Embeddings**: HuggingFace `sentence-transformers/all-MiniLM-L6-v2`.

## ⚙️ Configuration

Create a `backend/.env` file with the following:

```ini
GEMINI_API_KEY=your_gemini_key
HF_API_TOKEN=your_huggingface_token
```

## 📦 Installation & Setup

### Backend
1. `cd backend`
2. `pip install -r requirements.txt`
3. `uvicorn main:app --reload`

### Frontend
1. `cd frontend`
2. `npm install`
3. `npm run dev`

## 🌍 Deployment

- **Frontend**: Deployed on Firebase Hosting.
- **Backend**: Optimized for Render (512MB RAM Free Tier).
- **Firestore**: Requires custom vector index configuration for `document_chunks`.

---
*Created with ❤️ by Antigravity AI*
