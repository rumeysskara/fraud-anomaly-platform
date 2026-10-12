---
name: technical-docs
description: "Tüm adımlar bittikten sonra docs/step*.md ve reports/ çıktılarından docs/technical_doc.md ve README.md'yi teslim kalitesinde yazarken kullan."
---

# Technical Documentation & README

## Girdi
docs/step0.md ... docs/step10.md, reports/ altındaki metrik tabloları, configs/*.yaml, reports/reviews/

## docs/technical_doc.md yapısı (Türkçe)
1. Özet: problem, yaklaşım, ana sonuçlar (holdout metrikleri tablosu)
2. Mimari: katman diyagramı (Mermaid), veri akışı (batch + online), kullanılan tasarım desenleri ve nerede
3. Veri: join, eksik veri, kolon tipi tespiti, yüksek cardinality, entity proxy kararı ve gerekçesi,
   TransactionDT referans tarih varsayımı, zaman bazlı split
4. Feature engineering: grup bazlı tablo, leakage önlemleri
5. Anomali katmanları: her katmanın yöntemi, neden seçildi, explain çıktısı
6. Skor birleştirme: normalizasyon, ağırlıklar, alternatiflerle karşılaştırma
7. **Context Adjust (detaylı)**: her kural için tablo (id, koşul, etki, gerekçe), tavan mekanizması,
   önce/sonra FP tablosu, kural bazlı ablation, yorum
8. **Rule Engine (detaylı)**: şema, 8-10+ kural tablosu, priority, conflict resolution algoritması ve örneği,
   explainability JSON örneği, kuralların final skora/karara etkisi
9. RAG: knowledge base, chunking, embedding modeli, vector search, prompt şablonu, 3 örnek sorgu
10. Multi-agent: agent rolleri, mesaj şeması, delegation akışı (sequence diyagram), hata yönetimi, örnek trace
11. API: endpoint tablosu, örnek istek/yanıt, DI container yapısı
12. Sınırlar ve gelecek iş

## README.md
Kurulum (Python, venv, `make install`), veri indirme ve yerleşimi, Ollama kurulumu ve modeller,
`make pipeline` (ve `SAMPLE_N` ile hızlı deneme), `make rag-index`, `make api`, örnek curl, testler, klasör yapısı,
dokümana link. Komutların hepsi gerçekten çalıştırılıp doğrulanmış olmalı.

## Kurallar
- Sayılar uydurulmaz; her metrik reports/ altındaki bir dosyadan gelir ve kaynağı belirtilir.
- Geliştirme agent'larından (.claude/agents) bahsedilmez; ürün mimarisi anlatılır.
