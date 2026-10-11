---
name: fastapi-service
description: "Adım 10 + bonus. FastAPI ile /score, /explain, /rules/evaluate, /rag/query endpoint'lerini yazarken ve dependency_injector container'ını kurarken kullan."
---

# FastAPI Service + Dependency Injection

## Girdi
- Tüm önceki adımların servisleri (detectors, aggregator, context, rules, RAG, agents)

## Çıktı
- src/api/ (main.py, routers/, schemas.py, dependencies)
- src/container.py (DeclarativeContainer, tüm servisler)
- tests/api/ (TestClient + container override)
- docs/step10.md (endpoint tablosu, örnek istek/yanıt)

## Endpoint'ler
| Endpoint | Metot | Amaç |
|---|---|---|
| /score | POST | İşlem(ler) için layer skorları, raw, adjusted skor |
| /explain | POST | Skorun katman katkıları, context düzeltmeleri, kural gerekçeleri, (opsiyonel) RAG açıklaması |
| /rules/evaluate | POST | Rule engine değerlendirmesi: tetiklenen/bastırılan kurallar, karar |
| /rag/query | POST | Policy sorgusu: retrieve + LLM yanıtı + kaynaklar |
| /health | GET | Servis ve bağımlılık durumu (Ollama, index) |
| /rules | GET | Yüklü kuralların listesi |
| /rules/reload | POST | Kural dosyalarını yeniden yükle (kod değişmeden yeni kural) |
| /agents/analyze | POST | (Opsiyonel) Adım 9 multi-agent akışını tetikler, trace döner |

`/rules/evaluate` isteği opsiyonel `rules` alanı alabilir: istekle gelen JSON kural seti o istek için kullanılır.
`/score` ham işlem alanlarını (TransactionAmt, card1, addr1, ... ) kabul eder; feature'ları `transform_one`
ile kendisi üretir.

## Tasarım
- Router'lar ayrı dosyalarda (`routers/score.py`, `explain.py`, `rules.py`, `rag.py`).
- Pydantic v2 request/response şemaları; örnek payload'lar OpenAPI'de görünür.
- Endpoint'ler iş mantığı içermez; ince katman, servis çağırır.
- Global hata işleyici (422/404/500 tutarlı JSON), request id, logging.
- Batch destek: /score birden fazla işlem alabilir (boyut sınırlı).

## Dependency Injection (bonus)
- `dependency_injector`: `Container` içinde Configuration, Singleton (modeller, vector store, LLM client,
  rule set), Factory (request-scoped nesneler), Resource (başlatma/kapatma gerektirenler).
- `wiring_config` ile router modülleri wire edilir; endpoint'ler `@inject` + `Depends(Provide[...])`.
- Startup'ta: modeller/yapılandırma yüklenir, kural şeması doğrulanır, indeks kontrol edilir.
- Testlerde `container.<provider>.override(...)` ile mock.

## Kurallar
- Gerçek model/artifact'ler `artifacts/` altından yüklenir (fit edilmiş detector'lar kaydedilmiş olmalı);
  API istek anında eğitim yapmaz.
- API yanıtlarında isFraud alanı yok.
- Ollama kapalıyken /rag/query ve /explain degrade çalışır (hata değil, retrieval-only yanıt).

## Kontrol listesi
- [ ] 4 zorunlu endpoint + /health çalışıyor, Swagger'da görünüyor
- [ ] Container tüm bağımlılıkları yönetiyor, servis içinde `new` yok
- [ ] API testleri container override ile geçiyor
- [ ] `uvicorn src.api.main:app` ile ayağa kalkıyor, README'de komut var
- [ ] Örnek curl istekleri docs/step10.md'de
- [ ] docs/step10.md yazıldı
