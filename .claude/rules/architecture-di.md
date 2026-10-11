# Mimari ve Dependency Injection Kuralları

## Ortak arayüzler (src/core/interfaces.py, ABC / Protocol)
- `Detector`: `fit(df) -> self`, `score(df) -> pd.Series` ([0,1]), `explain(row) -> dict`
- `Aggregator`: `aggregate(scores: dict[str, pd.Series]) -> pd.Series`
- `ContextAdjuster`: `adjust(df, raw_score) -> AdjustedResult`
- `RuleEvaluator`: `evaluate(record, anomaly_score) -> RuleResult`
- `Retriever`: `retrieve(query, k) -> list[Chunk]`
- `LLMClient`: `generate(prompt, context) -> str` (Ollama implementasyonu)

## Tasarım desenleri (bonus puan, dokümanda belirt)
- Strategy: Detector ve Aggregator varyantları
- Factory: detector/rule/agent oluşturma
- Chain of Responsibility / Pipeline: skor -> context -> rule -> açıklama akışı
- Observer veya Mediator: agent'lar arası mesajlaşma
- Repository: veri yükleme, kural yükleme, knowledge base erişimi

## Dependency Injection
- `dependency_injector` kütüphanesi; tek bir `src/container.py` içinde `DeclarativeContainer`.
- Config: `providers.Configuration()` ile `configs/*.yaml` yüklenir.
- Singleton: model, vector store, LLM client, rule set. Factory: request-scoped nesneler.
- Servis/sınıf içinde bağımlılık `new` ile oluşturulmaz; constructor ile enjekte edilir.
- FastAPI endpoint'leri `Provide[Container.x]` + `@inject` kullanır; global değişken yok.
- Testlerde `container.x.override(mock)` ile sahte bağımlılık verilir.

## Katman bağımlılık yönü
api -> agents -> (rag, rules, context, scoring, detection) -> features -> data
Ters yönde import yasak (döngüsel bağımlılık oluşturma).
