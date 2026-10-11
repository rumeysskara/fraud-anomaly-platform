---
name: multi-agent
description: "Adım 9. Birden fazla agent, agent-to-agent communication ve task delegation içeren orkestrasyon yapısını kurarken kullan. Local LLM ile çalışır."
---

# Agentic AI Orchestration

## Girdi
- Mevcut servisler: feature, scoring, context, rule, RAG (container üzerinden)

## Çıktı
- src/agents/ (base agent, message bus, orchestrator, agent'lar, workflow tanımları)
- configs/agents.yaml (agent rolleri, workflow adımları, retry/timeout)
- reports/agents/trace_*.json (örnek çalışma izleri)
- docs/step9.md (mimari diyagram, mesaj formatı, örnek akış)

## Agent'lar
1. **OrchestratorAgent**: isteği alır, workflow'u planlar, görevleri delege eder, sonuçları birleştirir.
2. **FeatureAgent**: ham işlem/entity için feature üretir.
3. **ScoringAgent**: katman skorları + aggregation + context adjust.
4. **RuleAgent**: rule engine değerlendirmesi, kararı ve açıklamayı üretir.
5. **KnowledgeAgent (RAG)**: ilgili policy'leri getirir.
6. **ExplainerAgent (LLM)**: tüm sonuçlardan insan okuyabilir gerekçe/rapor yazar.
(İstersen ReviewerAgent: sonucu tutarlılık için denetler.)

## İletişim
- Typed mesaj şeması (pydantic): `AgentMessage {id, correlation_id, sender, receiver, type, payload, timestamp}`
- Basit in-process message bus / mediator (Observer-Mediator deseni); agent'lar birbirini doğrudan
  import etmez, bus üzerinden konuşur.
- Mesaj tipleri: TASK_REQUEST, TASK_RESULT, TASK_ERROR, QUERY, INFO.

## Task delegation
- Orchestrator workflow'u (configs/agents.yaml) okur: adım, hedef agent, girdi, bağımlılıklar.
- Bağımsız adımlar paralel (örn. ScoringAgent ve KnowledgeAgent), bağımlı olanlar sıralı.
- Hata yönetimi: timeout, retry, bir agent düşerse degrade mod (örn. LLM yoksa şablon açıklama).
- Her çalışmanın izi (kim kime ne gönderdi) trace dosyasına yazılır.

## Agentic davranış (LLM'in gerçek rolü)
- Orchestrator serbest metin görevi alabilir (örn. "TransactionID 2987004'ü incele ve inceleme notu yaz").
  Local LLM ile plan çıkarır (hangi agent'lar, hangi sırayla), plan JSON şemasıyla doğrulanır;
  LLM yoksa veya plan geçersizse configs/agents.yaml'daki varsayılan workflow'a düşer.
- En az bir agent başka bir agent'a alt görev delege eder (örn. RuleAgent belirsiz durumda KnowledgeAgent'a QUERY atar).

## Kurallar
- Agent'lar container'dan inject edilir, yeni servis nesnesi içinde yaratılmaz.
- LLM karar vermez; skor/karar deterministik servislerden gelir, LLM yalnızca açıklama ve yönlendirme için.
- Local LLM (Ollama); testlerde mock LLM.

## Kontrol listesi
- [ ] En az 4 agent, ortak BaseAgent arayüzü
- [ ] Agent'lar arası mesajlaşma bus üzerinden, doğrudan çağrı yok
- [ ] Delegation: orchestrator workflow'dan görev dağıtıyor
- [ ] Hata/timeout senaryosu testi
- [ ] Örnek trace dosyası ve diyagram dokümanda
- [ ] docs/step9.md yazıldı
