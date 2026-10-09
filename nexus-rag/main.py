import os
import json
import uuid
import pymupdf
import ollama
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.http import models

app = FastAPI(
    title="NexusRAG Engine & OmniDocs Studio",
    description="Privacy-First Multi-Tenant RAG API with Cross-Encoder & Ollama",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "desktop_ui")
REGISTRY_FILE = os.path.join(BASE_DIR, "documents_registry.json")

# 1. Altyapı ve Modeller
print("Modeller yerel belleğe yükleniyor...")
bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "enterprise_rag_chunks"
OLLAMA_MODEL = "llama3.2"

# Koleksiyonu Garanti Et
try:
    collections = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
        )
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="tenant_id",
            field_schema=models.PayloadSchemaType.KEYWORD
        )
except Exception as e:
    print(f"Qdrant collection setup note: {e}")

# Static UI mount
if os.path.exists(UI_DIR):
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

@app.get("/")
async def root():
    index_path = os.path.join(UI_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "OmniDocs Studio Backend is Running"}

@app.get("/style.css")
async def get_css():
    return FileResponse(os.path.join(UI_DIR, "style.css"))

@app.get("/app.js")
async def get_js():
    return FileResponse(os.path.join(UI_DIR, "app.js"))

@app.get("/sample.pdf")
async def get_sample_pdf():
    sample_path = os.path.join(BASE_DIR, "sample.pdf")
    if os.path.exists(sample_path):
        return FileResponse(sample_path, media_type="application/pdf")
    raise HTTPException(status_code=404, detail="sample.pdf bulunamadı")

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

def parse_page_range(range_str: str, max_pages: int) -> List[int]:
    if not range_str or not range_str.strip():
        return list(range(max_pages))
    selected = set()
    for part in range_str.replace(" ", "").split(","):
        if "-" in part:
            sub = part.split("-")
            if len(sub) == 2 and sub[0].isdigit() and sub[1].isdigit():
                start, end = max(1, int(sub[0])), min(max_pages, int(sub[1]))
                for p in range(start, end + 1):
                    selected.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                selected.add(p - 1)
    res = sorted(list(selected))
    return res if res else list(range(max_pages))

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

# 3. Doküman Yükleme & Bölümleme Endpoint'i
@app.post("/api/v1/documents/upload")
async def upload_document(
    tenant_id: str = Form(...),
    file: UploadFile = File(...),
    section_name: Optional[str] = Form(None),
    page_range: Optional[str] = Form(None),
    chunk_size: Optional[int] = Form(500),
    overlap: Optional[int] = Form(100)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece PDF dosyaları kabul edilir.")

    file_bytes = await file.read()
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    total_pages = len(doc)
    target_pages = parse_page_range(page_range or "", total_pages)
    
    all_texts = []
    all_payloads = []
    doc_id = str(uuid.uuid4())

    for page_idx in target_pages:
        page_text = doc.load_page(page_idx).get_text("text").strip()
        if not page_text:
            continue
        chunks = chunk_text(page_text, chunk_size=chunk_size or 500, overlap=overlap or 100)
        for c_idx, chunk in enumerate(chunks):
            all_texts.append(chunk)
            all_payloads.append({
                "tenant_id": tenant_id,
                "document_id": doc_id,
                "file_name": file.filename,
                "section_name": section_name or "Genel",
                "page_number": page_idx + 1,
                "chunk_index": c_idx,
                "text": chunk
            })

    if not all_texts:
        raise HTTPException(status_code=400, detail="Seçilen sayfalarda veya PDF içinde metin bulunamadı.")

    vectors = bi_encoder.encode(all_texts, normalize_embeddings=True).tolist()
    points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
        for v, p in zip(vectors, all_payloads)
    ]
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    # Registry güncelle
    try:
        registry = []
        if os.path.exists(REGISTRY_FILE):
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                registry = json.load(f)
        registry.append({
            "id": doc_id,
            "name": file.filename,
            "tenant_id": tenant_id,
            "section": section_name or "Genel",
            "pages": len(target_pages),
            "chunks": len(points)
        })
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Registry log error: {e}")

    return {
        "status": "SUCCESS",
        "tenant_id": tenant_id,
        "document_id": doc_id,
        "indexed_chunks": len(points),
        "pages_processed": len(target_pages)
    }

# 4. Arama ve LLM Cevap Endpoint'i
@app.post("/api/v1/search/query", response_model=QueryResponse)
async def query_rag(req: QueryRequest):
    query_vector = bi_encoder.encode(req.query, normalize_embeddings=True).tolist()

    query_filter = models.Filter(
        must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=req.tenant_id))]
    ) if req.tenant_id != "all" else None

    search_result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=12
    )

    if not search_result.points:
        return QueryResponse(
            answer=f"'{req.tenant_id}' bölümünde bu konuyla ilgili doküman kaydı bulunamadı.",
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
            relevance_score=round(max(0.1, min(0.99, (c["score"] + 5) / 10)), 3),
            excerpt=p["text"][:140] + "..."
        ))

    system_prompt = (
        "Sen kurumsal, tamamen gizli ve kapalı devre bir doküman asistanısın. YALNIZCA bağlamdaki bilgileri kullan. "
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
