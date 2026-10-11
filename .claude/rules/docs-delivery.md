# Dokümantasyon ve Teslim Kuralları

## Teslim edilecekler
1. Source code (GitHub repo, düzenli commit geçmişi)
2. Teknik doküman: docs/technical_doc.md
3. README.md: kurulum, Ollama adımları, veri yerleşimi, çalıştırma komutları

## Adım bazlı doküman
Her adım için `docs/stepN.md` yaz: ne yapıldı, neden, çıktı dosyası ve şeması,
bir sonraki adımın girdisi, bilinen sınırlar. `isFraud` kullanımı notu zorunlu.

## Teknik doküman içeriği
- Mimari diyagram (katmanlar, agent akışı), kullanılan tasarım desenleri
- Veri: birleştirme, eksik veri, yüksek cardinality kararları, entity proxy gerekçesi
- Anomali katmanları ve skor birleştirme yönteminin NEDEN seçildiği
- Adım 6 (Context Adjust) detaylı: her context kuralı, gerekçe, parametreler,
  false positive'e etkisi (önce/sonra sayısal metrik)
- Adım 7 (Rule Engine) detaylı: 8-10+ kural tablosu, öncelik, conflict resolution,
  explainability çıktı örneği
- RAG: knowledge base içeriği, embedding modeli, chunking, retrieval örneği
- Agent orkestrasyonu: agent rolleri, mesaj formatı, delegation akışı
- API: endpoint tablosu, örnek istek/yanıt
- Sınırlar ve gelecek iş

## Dil
Teknik doküman ve README Türkçe; kod, değişken ve yorum satırları İngilizce.

## Git
Adım başına en az bir commit, Conventional Commits (feat:, fix:, docs:, test:, chore:).
