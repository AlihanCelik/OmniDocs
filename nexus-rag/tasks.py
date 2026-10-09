import os
import uuid
import pymupdf
from celery import Celery
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Celery ve Redis Bağlantısı
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("rag_tasks", broker=REDIS_URL, backend=REDIS_URL)

COLLECTION_NAME = "enterprise_rag_chunks"

# Worker başladığında modelleri hafızaya alır
bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100):
    words = text.split()
    chunks, current_chunk, current_len = [], [], 0
    for word in words:
        current_chunk.append(word)
        current_len += len(word) + 1
        if current_len >= chunk_size:
            chunks.append(" ".join(current_chunk))
            overlap_words = int(len(current_chunk) * (overlap / chunk_size))
            current_chunk = current_chunk[-max(1, overlap_words):]
            current_len = sum(len(w) + 1 for w in current_chunk)
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

@celery_app.task(name="process_pdf_document")
def process_pdf_document(file_bytes: bytes, filename: str, tenant_id: str, document_id: str):
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    all_texts = []
    all_payloads = []

    for page_idx in range(len(doc)):
        page_text = doc.load_page(page_idx).get_text("text").strip()
        if not page_text:
            continue
        chunks = chunk_text(page_text)
        for c_idx, chunk in enumerate(chunks):
            all_texts.append(chunk)
            all_payloads.append({
                "tenant_id": tenant_id,
                "document_id": document_id,
                "file_name": filename,
                "page_number": page_idx + 1,
                "chunk_index": c_idx,
                "text": chunk
            })

    if not all_texts:
        return {"status": "FAILED", "reason": "No text extracted"}

    vectors = bi_encoder.encode(all_texts, normalize_embeddings=True).tolist()
    points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
        for v, p in zip(vectors, all_payloads)
    ]
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    return {
        "status": "COMPLETED",
        "tenant_id": tenant_id,
        "document_id": document_id,
        "indexed_chunks": len(points),
        "total_pages": len(doc)
    }
