import os
import uuid
import pymupdf
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models

print("1. Model ve Qdrant bağlantısı hazırlanıyor...")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "enterprise_rag_chunks"

# Koleksiyon yoksa 384 vektör boyutu ile oluştur
collections = [c.name for c in qdrant.get_collections().collections]
if COLLECTION_NAME not in collections:
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
    )
    # Şirket/Tenant izolasyonu için filtre indeksi aç
    qdrant.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="tenant_id",
        field_schema=models.PayloadSchemaType.KEYWORD
    )
    print(f"Koleksiyon açıldı: {COLLECTION_NAME}")

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100):
    words = text.split()
    chunks = []
    current_chunk = []
    current_len = 0

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

def process_and_index_pdf(file_path: str, tenant_id: str, document_id: str):
    print(f"2. PDF Okunuyor: {file_path}")
    doc = pymupdf.open(file_path)
    all_texts = []
    all_payloads = []

    for page_idx in range(len(doc)):
        page = doc.load_page(page_idx)
        page_text = page.get_text("text").strip()
        if not page_text:
            continue

        chunks = chunk_text(page_text, chunk_size=500, overlap=100)
        for c_idx, chunk in enumerate(chunks):
            all_texts.append(chunk)
            all_payloads.append({
                "tenant_id": tenant_id,
                "document_id": document_id,
                "file_name": os.path.basename(file_path),
                "page_number": page_idx + 1,
                "chunk_index": c_idx,
                "text": chunk
            })

    print(f"Toplam {len(doc)} sayfa okundu, {len(all_texts)} parça metin çıkarıldı.")
    if not all_texts:
        print("Uyarı: PDF içeriğinde okunabilir metin bulunamadı!")
        return

    print("3. Vektörler hesaplanıyor (Embedding)...")
    vectors = model.encode(all_texts, show_progress_bar=True, normalize_embeddings=True)

    print("4. Qdrant'a yükleniyor...")
    points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector.tolist(),
            payload=payload
        )
        for vector, payload in zip(vectors, all_payloads)
    ]

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print("İşlem Başarılı! Doküman parçaları Qdrant'a yazıldı.")

if __name__ == "__main__":
    test_pdf = "sample.pdf"
    if os.path.exists(test_pdf):
        process_and_index_pdf(file_path=test_pdf, tenant_id="company_test", document_id="doc_1")
    else:
        print(f"Hata: Lütfen proje dizinine '{test_pdf}' adında bir PDF koyup tekrar çalıştır.")
