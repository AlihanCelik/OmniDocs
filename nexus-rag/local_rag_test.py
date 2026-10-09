import ollama
from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.http import models

print("1. Modeller yerel belleğe yükleniyor (Dışarıya veri çıkışı YOK)...")
bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "enterprise_rag_chunks"
LOCAL_LLM = "llama3.2"

def private_rag_query(query: str, tenant_id: str):
    print(f"\n[LOKAL SORGU] Soru: '{query}' | Şirket/Tenant: {tenant_id}")
    
    # 1. Yerel Vektörleştirme
    query_vector = bi_encoder.encode(query, normalize_embeddings=True).tolist()

    # 2. Yerel Qdrant Tenant Filtreli Arama
    search_result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
        ),
        limit=10
    )

    if not search_result.points:
        print("Sonuç bulunamadı.")
        return

    # 3. Yerel Cross-Encoder Reranking
    pairs = [[query, pt.payload["text"]] for pt in search_result.points]
    scores = cross_encoder.predict(pairs)

    ranked = []
    for pt, score in zip(search_result.points, scores):
        ranked.append({"score": float(score), "payload": pt.payload})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    top_chunks = ranked[:3]

    # 4. Bağlam Hazırlığı
    context = ""
    for c in top_chunks:
        p = c["payload"]
        context += f"\n[Dosya: {p['file_name']}, Sayfa: {p['page_number']}]\n{p['text']}\n"

    system_prompt = (
        "Sen kurumsal, tamamen gizli ve kapalı devre bir doküman asistanısın.\n"
        "Yalnızca verilen bağlamdaki bilgileri kullan. Her bilginin sonuna [Kaynak: <dosya>, Sayfa: <no>] ekle. "
        "Bağlam dışı bilgi verme veya tahmin yürütme."
    )
    user_prompt = f"BAĞLAM:\n{context}\n\nSORU:\n{query}\n\nCEVAP:"

    print("2. Ollama (Local Llama 3.2) cevabı üretiyor...\n")
    response = ollama.chat(
        model=LOCAL_LLM,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        options={"temperature": 0.1}
    )

    print("--- ÜRETİLEN YEREL CEVAP ---")
    print(response["message"]["content"])

if __name__ == "__main__":
    private_rag_query("Dokümanda geçen phrasal verbler nelerdir?", tenant_id="company_test")
