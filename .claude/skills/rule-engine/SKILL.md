---
name: rule-engine
description: "Adım 7. YAML/JSON tabanlı configurable fraud rule engine yazarken veya kural eklerken kullan. If-then değerlendirme, priority, conflict resolution ve explainability çıktısı içerir."
---

# Rule Engine

## Girdi
- reports/scores/adjusted_score.parquet, data/processed/features.parquet

## Çıktı
- configs/rules.yaml (en az 8-10 gerçekçi kural)
- src/rules/ (loader, schema, evaluator, conflict resolver, explainer)
- reports/rules/rule_hits.parquet: TransactionID, triggered_rules, final_decision, final_score
- docs/step7.md (kural tablosu, öncelik, conflict resolution, örnek çıktı)

## Kural şeması (configs/rules.yaml)
- id, name, description, priority (1 = en yüksek), severity (low|medium|high|critical)
- condition: all / any / not ile iç içe; operatörler: >, >=, <, <=, ==, !=, in, not_in, between, is_null, contains
- action: { risk_boost: float, flag: str, decision: review|block|allow }
- tags, enabled
- Şema pydantic ile doğrulanır; geçersiz kural startup'ta reddedilir. JSON da desteklenir.

## Zorunlu kurallar (en az 8-10, kendi tasarımınla)
Yüksek tutar + yabancı ülke + gece; velocity (kısa sürede çok işlem); yeni cihaz + yüksek tutar;
email domain uyuşmazlığı (P vs R); daha önce görülmeyen kart-adres kombinasyonu;
tutar sapması (user_avg'ın N katı); ardışık küçük tutarlı işlemler (card testing);
hafta sonu gece yüksek tutar; kimliksiz (has_identity=false) yüksek tutar;
trusted-user allow kuralı (düşük riskli, uzun geçmişli entity).

## Dinamik çalışma (case: "sisteme eklenebilmesi ve dinamik çalıştırılabilmesi")
- `RuleRepository`: YAML ve JSON dosyalarından yükler, `reload()` destekler.
- `RuleEngine.evaluate(record, anomaly_score, rules=None)`: `rules` verilirse istekte gelen kural seti
  (JSON) doğrulanıp o anda kullanılır; verilmezse yüklü set.
- `configs/rules.yaml` ile birlikte örnek `configs/rules_extra.json` (en az 2 kural) JSON desteğini kanıtlar.
- Koşullar feature adlarına göre yazılır; bilinmeyen feature adı startup'ta hata verir.

## Conflict resolution
1. Priority değeri küçük olan kazanır.
2. Aynı priority'de severity yüksek olan kazanır.
3. Aynı seviyede karar önceliği: block > review > allow.
4. `allow`, yalnızca daha yüksek priority'de bir block/review yoksa uygulanır.
5. risk_boost'lar toplanır ama tavanlıdır (final score [0,1] clip).
Uygulanan ve bastırılan kurallar ve bastırılma nedeni çıktıda listelenir.

## Anomali skoruyla birlikte çalışma
Girdi: record + adjusted_score. Çıktı: final_score = clip(adjusted_score + sum(boosts)),
final_decision (kural kararı + skor eşiği birlikte).

## Explainability çıktısı
```json
{
  "triggered_rules": [{"id": "R01", "name": "...", "priority": 1, "severity": "high"}],
  "suppressed_rules": [{"id": "R09", "reason": "R01 daha yüksek priority"}],
  "final_decision": "review",
  "reasons": ["Gece 02:00, tutar entity ortalamasının 8x'i, yabancı adres"],
  "anomaly_score": 0.71,
  "adjusted_score": 0.66,
  "final_score": 0.83
}
```
Her `reason` metni kural şablonundan ve gerçek değerlerden üretilir (kural YAML'ında message template).

## Kontrol listesi
- [ ] Kurallar kod değiştirmeden YAML'dan yüklenir (hot reload opsiyonel)
- [ ] Geçersiz kural şeması reddediliyor
- [ ] 8-10+ kural, gerçekçi, kendi tasarımınız
- [ ] Priority + conflict resolution gösteren örnek (çakışan kurallı kayıt)
- [ ] Her kural için pytest (tetiklenen / tetiklenmeyen)
- [ ] isFraud kural koşulunda YOK
- [ ] docs/step7.md detaylı
