---
name: rag-pipeline
description: "Adım 8. Fraud policy knowledge base, embedding, vector search ve local LLM (Ollama) context injection ile RAG tabanlı açıklama/reasoning akışı kurarken kullan."
---

# RAG Pipeline (local)

## Girdi
- Rule engine çıktısı ve skor çıktıları (explain payload), knowledge_base/*.md

## Çıktı
- knowledge_base/*.md (örnek fraud policy / kural dokümanları, uydurma olabilir)
- src/rag/ (chunker, embedder, vector store, retriever, prompt builder, llm client, rag service)
- data/vector_store/ (FAISS/Chroma indeksi, gitignore)
- docs/step8.md, örnek sorgu-yanıt çıktıları

## Knowledge base
8-12 kısa doküman yaz (Türkçe veya İngilizce): card testing politikası, yüksek tutar eşikleri,
yabancı ülke işlem politikası, yeni cihaz doğrulama, velocity limitleri, trusted müşteri
istisnaları, gece/hafta sonu politikası, manuel inceleme (review) prosedürü, kural-ID -> politika eşlemesi.
Her dokümanda başlık, politika ID, ilgili kural ID'leri bulunur (retrieval kalitesini artırır).

## Pipeline
1. **Chunking**: başlığa göre bölme, 200-400 token, küçük overlap, metadata (doc, policy_id, rule_ids).
2. **Embedding**: Ollama `nomic-embed-text` (veya local sentence-transformers). Embedder arayüzle soyutlanır.
3. **Vector search**: FAISS (cosine / inner product normalize) veya Chroma; top-k (k=3-5) + opsiyonel
   metadata filtresi (tetiklenen kural ID'leri).
4. **LLM context injection**: prompt = sistem talimatı + anomali sonucu (skorlar, tetiklenen kurallar,
   context düzeltmeleri) + getirilen policy parçaları + soru. Yalnızca verilen bağlamdan cevap ver,
   kaynak policy ID'lerini belirt, bilmiyorsa "bilgi yok" de.
5. **LLM**: Ollama (örn. llama3.1:8b veya llama3.2:3b), temperature düşük (0-0.2), timeout ve retry.
6. **RAG reasoning akışı**: explain payload -> sorgu üret -> retrieve -> prompt -> LLM -> yapılandırılmış
   yanıt (özet, neden riskli, ilgili policy, önerilen aksiyon, kaynaklar).

## Kurallar
- Ücretli API YOK; tüm bileşenler local.
- LLM client ve embedder arayüzlerle soyutlanır, container'dan inject edilir; testlerde mock kullanılır.
- Ollama kapalıysa anlamlı hata/fallback (örn. sadece retrieval sonucu dön).
- Dokümanda en az 3 örnek sorgu ve getirilen parçaları göster.

## Kontrol listesi
- [ ] Knowledge base dokümanları var, kural ID'leriyle eşleşiyor
- [ ] İndeks oluşturma scripti (scripts/build_index.py)
- [ ] Retrieval testleri (doğru policy geliyor mu)
- [ ] LLM yanıtı kaynak policy ID'lerini içeriyor
- [ ] LLM/embedder mock'lanabiliyor (pytest Ollama olmadan geçer)
- [ ] docs/step8.md yazıldı
