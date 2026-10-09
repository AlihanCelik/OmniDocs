from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.http import models

print("1. Modeller yükleniyor (Bi-Encoder ve Cross-Encoder)...")
bi_encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
qdrant = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "enterprise_rag_chunks"

def search_and_rerank(query: str, tenant_id: str, top_k_dense: int = 10, top_k_final: int = 3):
    print(f"\n--- Soru: '{query}' (Tenant: {tenant_id}) ---")
    
    # 1. Soruyu vektörleştir
    query_vector = bi_encoder.encode(query, normalize_embeddings=True).tolist()

    # 2. Qdrant'ta Tenant İzolasyonlu Vektör Araması Yap (Bi-Encoder)
    search_result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id)
                )
            ]
        ),
        limit=top_k_dense
    )

    candidate_chunks = search_result.points
    print(f"Qdrant'tan gelen ilk aday sayısı: {len(candidate_chunks)}")

    if not candidate_chunks:
        print("Hiçbir sonuç bulunamadı (Farklı bir tenant olabilir veya koleksiyon boş).")
        return []

    # 3. Cross-Encoder ile Yeniden Sıralama (Reranking)
    # Model, [Soru, Metin] çiftlerini birlikte değerlendirir
    pairs = [[query, point.payload["text"]] for point in candidate_chunks]
    rerank_scores = cross_encoder.predict(pairs)

    # Parçaları yeni skorlarına göre sırala
    scored_candidates = []
    for point, score in zip(candidate_chunks, rerank_scores):
        scored_candidates.append({
            "score": float(score),
            "text": point.payload["text"],
            "page": point.payload["page_number"],
            "file": point.payload["file_name"]
        })

    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_results = scored_candidates[:top_k_final]

    # Sonuçları ekrana yazdır
    print(f"\n Cross-Encoder Tarafından Seçilen En İyi {len(top_results)} Parça:")
    for rank, res in enumerate(top_results, 1):
        print(f"\n[{rank}] (Skor: {res['score']:.4f}) - Dosya: {res['file']}, Sayfa: {res['page']}")
        print(f"Metin: {res['text'][:180]}...")

    return top_results

if __name__ == "__main__":
    # sample.pdf içindeki bir konuyla ilgili bir soru yaz
    test_soru = "Dokümanda geçen temel konu veya tanım nedir?"
    search_and_rerank(query=test_soru, tenant_id="company_test")
