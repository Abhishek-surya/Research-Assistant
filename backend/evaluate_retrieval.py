import asyncio
import os
import sys
import math

# Ensure backend directory is in path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables if they exist
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
from dotenv import load_dotenv
load_dotenv(dotenv_path=env_path)

from core.firebase import init_firebase
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from services.embedder import generate_embedding

# Mock dataset: list of dicts with 'query' and 'expected_source' (document_name or filename)
EVALUATION_DATASET = [
    {
        "query": "What is a polymorphic function in Python?",
        "expected_source": "thinkpython2.pdf" 
    },
    {
        "query": "How do you use the try and except keywords to handle exceptions?",
        "expected_source": "pythonlearn.pdf"
    },
    {
        "query": "What are the basic data types and how do you define a function?",
        "expected_source": "Python_Programming.pdf"
    },
    {
        "query": "What is the difference between a list and a tuple regarding mutability?",
        "expected_source": "thinkpython2.pdf"
    }
]

def cosine_similarity(v1, v2):
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0

async def evaluate():
    print("Initializing Firebase...")
    try:
        init_firebase()
    except ValueError as e:
        # Ignore error if already initialized
        pass
        
    db = firestore.client()
    chunks_ref = db.collection("document_chunks")
    
    print("Fetching all processed chunks from Firestore for local vector search...")
    # We fetch locally to avoid 'Missing vector index' errors on the Firestore side
    all_chunks = []
    docs = chunks_ref.where(filter=FieldFilter("status", "==", "processed")).stream()
    for doc in docs:
        data = doc.to_dict()
        emb = data.get("embedding")
        if emb:
            # Convert Firestore Vector object to list of floats
            emb_list = list(emb)
            all_chunks.append({
                "id": doc.id,
                "document_name": data.get("document_name", ""),
                "filename": data.get("filename", ""),
                "embedding": emb_list
            })
            
    print(f"Loaded {len(all_chunks)} chunks for evaluation.\n")
    
    total_queries = len(EVALUATION_DATASET)
    total_mrr = 0.0
    total_precision_at_5 = 0.0
    total_recall_at_5 = 0.0

    print(f"Starting evaluation over {total_queries} queries...\n")

    for i, item in enumerate(EVALUATION_DATASET, 1):
        query = item["query"]
        expected_source = item["expected_source"]
        
        print(f"--- Query {i}/{total_queries} ---")
        print(f"Q: '{query}'")
        print(f"Expected Source: '{expected_source}'")
        
        try:
            # 1. Generate query embedding
            query_embedding = generate_embedding(query)
            
            if not query_embedding:
                print("Error: Empty embedding returned.")
                continue
                
            # 2. Local Vector Search (Cosine Similarity)
            scored_chunks = []
            for chunk in all_chunks:
                score = cosine_similarity(query_embedding, chunk["embedding"])
                scored_chunks.append({
                    "document_name": chunk["document_name"],
                    "filename": chunk["filename"],
                    "score": score
                })
                
            # Sort by highest score descending and get top 5
            scored_chunks.sort(key=lambda x: x["score"], reverse=True)
            top_5_chunks = scored_chunks[:5]
                
            # 3. Calculate metrics for this query
            relevant_ranks = []
            for rank, chunk in enumerate(top_5_chunks, 1):
                doc_name = chunk["document_name"].lower()
                fname = chunk["filename"].lower()
                expected_lower = expected_source.lower()
                # Determine relevance based on matching the expected source document
                if expected_lower in doc_name or expected_lower in fname:
                    relevant_ranks.append(rank)
            
            # MRR (Mean Reciprocal Rank)
            mrr = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
            
            # Precision@5
            precision = len(relevant_ranks) / 5.0
            
            # Recall@5 (using Hit Rate@5 for document-level retrieval)
            recall = 1.0 if relevant_ranks else 0.0
            
            print(f"Retrieved top 5 chunks.")
            for rank, chunk in enumerate(top_5_chunks, 1):
                match = "*" if rank in relevant_ranks else " "
                print(f"  [{rank}] {match} {chunk.get('filename') or chunk.get('document_name') or 'Unknown'} (Score: {chunk.get('score', 0):.3f})")
            
            print(f"MRR: {mrr:.2f} | Precision@5: {precision:.2f} | Recall@5: {recall:.2f}\n")
            
            total_mrr += mrr
            total_precision_at_5 += precision
            total_recall_at_5 += recall
            
        except Exception as e:
            print(f"Error processing query: {e}\n")

    # Calculate overall metrics
    print("=== FINAL EVALUATION RESULTS ===")
    print(f"Mean Reciprocal Rank (MRR): {total_mrr / total_queries:.4f}")
    print(f"Mean Precision@5:           {total_precision_at_5 / total_queries:.4f}")
    print(f"Mean Recall@5 (Hit Rate):   {total_recall_at_5 / total_queries:.4f}")

if __name__ == "__main__":
    asyncio.run(evaluate())
