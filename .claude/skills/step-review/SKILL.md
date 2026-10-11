---
name: step-review
description: "Bir adım bittikten sonra, bir sonraki adıma geçmeden önce çıktıyı bağımsız olarak denetlerken kullan. Test, leakage, dosya alanı, doküman ve case gereksinimlerini kontrol eder; kod yazmaz."
---

# Step Review

Girdi: kontrol edilecek adım numarası (örn. "Adım 3"). Kod DEĞİŞTİRME; yalnızca rapor yaz.

## Kontroller
1. **Testler**: `make test` (yoksa `pytest -q`) çalıştır; sonucu kaydet.
2. **Lint**: `make lint` (yoksa `ruff check .`).
3. **Leakage**: `grep -rn "isFraud" src/ scripts/ configs/` → yalnızca `src/evaluation/` ve `src/data/loader.py`
   içinde geçebilir. Başka yerde varsa KIRMIZI.
4. **Zamansal sızıntı** (Adım 3+): entity/velocity hesaplarında `shift(1)` / `closed="left"` veya eşdeğeri var mı;
   ilk işlem testi var mı.
5. **Case maddeleri**: ilgili adımın skill dosyasındaki kontrol listesini tek tek işaretle.
   Ek olarak case'teki madde listesi (aşağıda) karşılanıyor mu.
6. **Doküman**: `docs/stepN.md` var mı; çıktı dosyası + şema + sonraki adımın girdisi + "isFraud kullanıldı mı" notu.
7. **Sözleşme**: yeni sınıflar `src/core/interfaces.py` arayüzlerini uyguluyor mu; container'a kaydedilmiş mi.
8. **Örneklem → tam veri**: tam veriyle çalıştırıldı mı, süre ve bellek notu var mı.

## Case madde listesi (adım -> beklenen)
- 1: join, eksik veri, otomatik kolon tipi, veri kalitesi, dağılım, yüksek cardinality
- 2: numeric/categorical/datetime, null ratio, outlier, distribution, rare combination, kolon ilişkileri, entity pattern
- 3: temporal, entity (user_avg_amount, user_transaction_count), relational, context feature
- 4: column, multivariate, entity, temporal anomali; skorlar ayrı ayrı
- 5: normalize, weighted aggregation, final raw score, yöntem gerekçesi
- 6: business hours, weekend, trusted entity, FP azaltımı + kendi kuralların + dokümante etki
- 7: JSON/YAML, if-then, priority, conflict resolution, explainability, 8-10+ kural
- 8: knowledge base, embedding, vector search, LLM context injection, RAG reasoning
- 9: birden fazla agent, agent-to-agent iletişim, task delegation
- 10: /score, /explain, /rules/evaluate, /rag/query (FastAPI, modüler)
- Bonus: tasarım desenleri, dependency_injector container

## Çıktı
`reports/reviews/stepN_review.md`: her kontrol için ✅ / ⚠️ / ❌, kanıt (komut çıktısı, dosya:satır),
ve düzeltilmesi gerekenlerin kısa listesi. Sonuç satırı: "GEÇTİ" veya "DÜZELTME GEREKLİ".
