import os
import sys
import json
import uuid
import base64
import threading
from typing import List, Dict, Any, Optional
import pymupdf
import webview
from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.http import models
import ollama

# Sabitler ve Model Yapılandırması
COLLECTION_NAME = "enterprise_rag_chunks"
LOCAL_LLM = "llama3.2"
REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents_registry.json")

def parse_page_range(range_str: str, max_pages: int) -> List[int]:
    """
    Kullanıcının girdiği sayfa aralığını (örn: '1-5' veya '1, 3, 5-8') ayrıştırır.
    0-tabanlı sayfa indeksleri listesi döner.
    """
    if not range_str or not range_str.strip():
        return list(range(max_pages))
    
    selected_pages = set()
    parts = range_str.replace(" ", "").split(",")
    for part in parts:
        if "-" in part:
            sub = part.split("-")
            if len(sub) == 2 and sub[0].isdigit() and sub[1].isdigit():
                start = max(1, int(sub[0]))
                end = min(max_pages, int(sub[1]))
                for p in range(start, end + 1):
                    selected_pages.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                selected_pages.add(p - 1)
    
    res = sorted(list(selected_pages))
    return res if res else list(range(max_pages))

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
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

class DesktopAPI:
    def __init__(self):
        print("OmniDocs Studio: Modeller ve Vektör Veritabanı başlatılıyor...")
        self.bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self.cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.qdrant = QdrantClient(host="localhost", port=6333)
        self.ensure_collection_exists()
        self.registry = self._load_registry()

    def ensure_collection_exists(self):
        try:
            collections = [c.name for c in self.qdrant.get_collections().collections]
            if COLLECTION_NAME not in collections:
                self.qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
                )
                self.qdrant.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name="tenant_id",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
        except Exception as e:
            print(f"Qdrant koleksiyon kontrolü uyarısı: {e}")

    def _load_registry(self) -> List[Dict[str, Any]]:
        if os.path.exists(REGISTRY_FILE):
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Başlangıçta sample.pdf varsa kayda ekle
        default_docs = [
            {
                "id": "sample-doc-default",
                "name": "sample.pdf",
                "tenant_id": "company_test",
                "pages": 12,
                "chunks": 10,
                "section": "Genel"
            }
        ]
        self._save_registry(default_docs)
        return default_docs

    def _save_registry(self, data: List[Dict[str, Any]]):
        try:
            with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Registry kaydedilemedi: {e}")

    def get_system_status(self) -> Dict[str, Any]:
        """Sistem servislerinin (Qdrant, Ollama) canlılık durumunu döner."""
        qdrant_ok = False
        ollama_ok = False
        try:
            self.qdrant.get_collections()
            qdrant_ok = True
        except Exception:
            pass

        try:
            ollama.list()
            ollama_ok = True
        except Exception:
            pass

        return {
            "qdrant": qdrant_ok,
            "ollama": ollama_ok,
            "bi_encoder": True,
            "cross_encoder": True
        }

    def select_pdf_dialog(self) -> Optional[str]:
        """macOS Yerel Dosya Seçici Penceresi."""
        if not webview.windows:
            return None
        file_types = ('PDF Belgeleri (*.pdf)', '*.pdf')
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=file_types
        )
        if result and len(result) > 0:
            return result[0]
        return None

    def ingest_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        PDF Belgesini ayrıştırır, seçilen sayfa aralığı / bölüm filtresine göre chunklar,
        vektörleştirir ve Qdrant veritabanına indeksler.
        """
        file_path = params.get("file_path")
        file_data = params.get("file_data")
        file_name = params.get("file_name") or "document.pdf"
        tenant_id = params.get("tenant_id") or "company_test"
        section_name = params.get("section_name", "").strip()
        page_range = params.get("page_range", "").strip()
        chunk_size = int(params.get("chunk_size", 500))
        overlap = int(params.get("overlap", 100))

        # PDF Verisini Aç
        if file_path:
            resolved_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
            doc = pymupdf.open(resolved_path)
            file_name = os.path.basename(resolved_path)
        elif file_data:
            pdf_bytes = base64.b64decode(file_data)
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        else:
            raise ValueError("Dosya yolu veya dosya verisi sağlanmadı.")

        total_pages = len(doc)
        target_pages = parse_page_range(page_range, total_pages)

        all_texts = []
        all_payloads = []
        doc_id = str(uuid.uuid4())

        for p_idx in target_pages:
            page_text = doc.load_page(p_idx).get_text("text").strip()
            if not page_text:
                continue
            chunks = chunk_text(page_text, chunk_size=chunk_size, overlap=overlap)
            for c_idx, chunk in enumerate(chunks):
                all_texts.append(chunk)
                all_payloads.append({
                    "tenant_id": tenant_id,
                    "document_id": doc_id,
                    "file_name": file_name,
                    "section_name": section_name or "Genel",
                    "page_number": p_idx + 1,
                    "chunk_index": c_idx,
                    "text": chunk
                })

        if not all_texts:
            raise ValueError("Seçilen sayfalarda veya belgede okunabilir metin bulunamadı.")

        # Vektörleştirme
        vectors = self.bi_encoder.encode(all_texts, normalize_embeddings=True).tolist()
        points = [
            models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
            for v, p in zip(vectors, all_payloads)
        ]
        self.qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

        # Registry'ye kaydet
        doc_record = {
            "id": doc_id,
            "name": file_name,
            "tenant_id": tenant_id,
            "section": section_name or "Genel",
            "pages": len(target_pages),
            "chunks": len(points)
        }
        self.registry.append(doc_record)
        self._save_registry(self.registry)

        return {
            "status": "SUCCESS",
            "document_id": doc_id,
            "file_name": file_name,
            "tenant_id": tenant_id,
            "indexed_chunks": len(points),
            "pages_processed": len(target_pages)
        }

    def query_rag(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bölüm/Tenant odaklı semantik arama + Cross-Encoder Reranking + Yerel Ollama Soru-Cevap
        """
        query = params.get("query", "").strip()
        tenant_id = params.get("tenant_id", "company_test")
        top_k = int(params.get("top_k", 3))

        if not query:
            return {"answer": "Lütfen geçerli bir soru girin.", "citations": []}

        # 1. Bi-Encoder Vektör Arama
        query_vector = self.bi_encoder.encode(query, normalize_embeddings=True).tolist()
        
        query_filter = models.Filter(
            must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
        ) if tenant_id != "all" else None

        search_result = self.qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=12
        )

        if not search_result.points:
            return {
                "answer": f"'{tenant_id}' bölümünde bu konuyla ilgili herhangi bir doküman veya bilgi kaydı bulunamadı.",
                "citations": []
            }

        # 2. Cross-Encoder Reranking
        pairs = [[query, pt.payload["text"]] for pt in search_result.points]
        scores = self.cross_encoder.predict(pairs)

        ranked = []
        for pt, score in zip(search_result.points, scores):
            ranked.append({"score": float(score), "payload": pt.payload})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        top_chunks = ranked[:top_k]

        # 3. Bağlam ve Alıntılar
        context = ""
        citations = []
        for c in top_chunks:
            p = c["payload"]
            context += f"\n[Dosya: {p.get('file_name')}, Sayfa: {p.get('page_number')}]\n{p.get('text')}\n"
            citations.append({
                "file_name": p.get("file_name", "Doküman"),
                "page_number": p.get("page_number", 1),
                "relevance_score": round(max(0.1, min(0.99, (c["score"] + 5) / 10)), 3),
                "excerpt": p.get("text", "")[:150] + "..."
            })

        # 4. Ollama Yerel LLM Yanıtı
        system_prompt = (
            "Sen kurumsal, tamamen gizli ve kapalı devre bir doküman asistanısın. "
            "YALNIZCA sağlanan BAĞLAM içerisindeki bilgileri kullanarak kullanıcı sorusunu net, profesyonel "
            "ve eksiksiz bir Türkçe ile yanıtla. Her önemli bilginin veya maddenin sonuna "
            "[Kaynak: <dosya>, Sayfa: <sayfa_no>] formatında referans ekle. Bağlamda bulunmayan bilgileri asla uydurma."
        )
        user_prompt = f"BAĞLAM:\n{context}\n\nSORU:\n{query}\n\nCEVAP:"

        try:
            response = ollama.chat(
                model=LOCAL_LLM,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                options={"temperature": 0.1}
            )
            answer_text = response["message"]["content"]
        except Exception as e:
            answer_text = f"Ollama ile yanıt oluşturulurken hata meydana geldi: {str(e)}\n\nLütfen 'ollama run {LOCAL_LLM}' servisinin açık olduğundan emin olun."

        return {
            "answer": answer_text,
            "citations": citations
        }

    def raw_search_and_rerank(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Vektör Gezgini: Ham benzerlik sonuçları ve Cross-Encoder puanları."""
        query = params.get("query", "").strip()
        tenant_id = params.get("tenant_id", "company_test")
        top_k = int(params.get("top_k", 5))

        query_vector = self.bi_encoder.encode(query, normalize_embeddings=True).tolist()
        query_filter = models.Filter(
            must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
        ) if tenant_id != "all" else None

        search_result = self.qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=15
        )

        if not search_result.points:
            return []

        pairs = [[query, pt.payload["text"]] for pt in search_result.points]
        scores = self.cross_encoder.predict(pairs)

        results = []
        for pt, score in zip(search_result.points, scores):
            results.append({
                "score": float(score),
                "text": pt.payload["text"],
                "page": pt.payload.get("page_number", 1),
                "file": pt.payload.get("file_name", "Doküman")
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def list_documents(self) -> List[Dict[str, Any]]:
        return self.registry

    def delete_document(self, doc_id: str) -> bool:
        try:
            self.qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=doc_id))]
                    )
                )
            )
            self.registry = [d for d in self.registry if d["id"] != doc_id]
            self._save_registry(self.registry)
            return True
        except Exception as e:
            print(f"Doküman silinirken hata: {e}")
            return False

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_file = os.path.join(base_dir, "desktop_ui", "index.html")

    api = DesktopAPI()

    window = webview.create_window(
        title="OmniDocs AI — Enterprise Neural RAG Studio",
        url=f"file://{html_file}",
        js_api=api,
        width=1220,
        height=840,
        min_size=(1000, 700),
        background_color="#080b12",
        text_select=True
    )

    webview.start(debug=False)

if __name__ == "__main__":
    main()
