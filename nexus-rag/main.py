import os
import uuid
import pymupdf
import ollama
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.http import models

app = FastAPI(
    title="NexusRAG Engine",
    description="Privacy-First Multi-Tenant RAG API with Cross-Encoder & Ollama",
    version="1.0.0"
)

# 1. Altyapı ve Modeller
print("Modeller yerel belleğe yükleniyor...")
bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "enterprise_rag_chunks"
OLLAMA_MODEL = "llama3.2"

# 2. Şemalar
class QueryRequest(BaseModel):
    tenant_id: str
    query: str
    top_k: int = 3

class Citation(BaseModel):
    file_name: str
    page_number: int
    relevance_score: float
    excerpt: str

class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]

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

# 3. Doküman Yükleme Endpoint'i
@app.post("/api/v1/documents/upload")
async def upload_document(
    tenant_id: str = Form(...),
    file: UploadFile = File(...)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece PDF dosyaları kabul edilir.")

    file_bytes = await file.read()
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    
    all_texts = []
    all_payloads = []
    doc_id = str(uuid.uuid4())

    for page_idx in range(len(doc)):
        page_text = doc.load_page(page_idx).get_text("text").strip()
        if not page_text:
            continue
        chunks = chunk_text(page_text)
        for c_idx, chunk in enumerate(chunks):
            all_texts.append(chunk)
            all_payloads.append({
                "tenant_id": tenant_id,
                "document_id": doc_id,
                "file_name": file.filename,
                "page_number": page_idx + 1,
                "chunk_index": c_idx,
                "text": chunk
            })

    if not all_texts:
        raise HTTPException(status_code=400, detail="PDF içinde metin bulunamadı.")

    vectors = bi_encoder.encode(all_texts, normalize_embeddings=True).tolist()
    points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
        for v, p in zip(vectors, all_payloads)
    ]
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    return {
        "status": "SUCCESS",
        "tenant_id": tenant_id,
        "document_id": doc_id,
        "indexed_chunks": len(points)
    }

# 4. Arama ve LLM Cevap Endpoint'i
@app.post("/api/v1/search/query", response_model=QueryResponse)
async def query_rag(req: QueryRequest):
    query_vector = bi_encoder.encode(req.query, normalize_embeddings=True).tolist()

    search_result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=req.tenant_id))]
        ),
        limit=10
    )

    if not search_result.points:
        return QueryResponse(
            answer="Bu şirket için ilgili doküman veya kayıt bulunamadı.",
            citations=[]
        )

    # Reranking
    pairs = [[req.query, pt.payload["text"]] for pt in search_result.points]
    scores = cross_encoder.predict(pairs)

    ranked = []
    for pt, score in zip(search_result.points, scores):
        ranked.append({"score": float(score), "payload": pt.payload})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    top_chunks = ranked[:req.top_k]

    context = ""
    citations = []
    for c in top_chunks:
        p = c["payload"]
        context += f"\n[Dosya: {p['file_name']}, Sayfa: {p['page_number']}]\n{p['text']}\n"
        citations.append(Citation(
            file_name=p["file_name"],
            page_number=p["page_number"],
            relevance_score=round(c["score"], 4),
            excerpt=p["text"][:140] + "..."
        ))

    system_prompt = (
        "Sen gizli kurumsal doküman asistanısın. YALNIZCA bağlamdaki bilgileri kullan. "
        "Her bilginin sonuna [Kaynak: <dosya>, Sayfa: <no>] ekle. Bilgi yoksa uydurma."
    )
    user_prompt = f"BAĞLAM:\n{context}\n\nSORU:\n{req.query}\n\nCEVAP:"

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        options={"temperature": 0.1}
    )

    return QueryResponse(
        answer=response["message"]["content"],
        citations=citations
    )
