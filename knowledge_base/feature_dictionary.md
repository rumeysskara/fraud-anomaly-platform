---
doc_type: feature_dictionary
---
# Feature Sözlüğü

Kurallarda, context düzeltmelerinde ve açıklama metinlerinde geçen feature'ların anlamı. Tüm entity tabanlı feature'lar yalnızca GEÇMİŞ işlemlerden hesaplanır (satırın kendisi ve sonraki satırlar sayılmaz). Entity, `card1 + addr1` ile tanımlanan yaklaşık bir kart grubudur; kişi değildir ve addr1 boşluğu tek bir seviye sayılır.

## Tutar feature'ları

| Feature | Anlamı |
|---|---|
| TransactionAmt | İşlem tutarı (USD varsayımı). Küçük tutar eşiği fit q10 (25,95), yüksek tutar eşiği fit q95 (441,95); context katmanında yüksek tutar fit q90'dır. |
| amt_ratio_to_ent_avg | Tutarın entity'nin geçmiş ortalama tutarına oranı. R06 için 5 ve üzeri sapmadır. |
| amt_zscore_ent | Tutarın entity geçmişine göre z-skoru. Güvenilir entity tanımında (R10, C4) mutlak değeri en çok 2 olmalıdır. |
| amt_has_3dec | Tutar 3 ondalıklıysa 1. Olası döviz çevrimi göstergesi (topluluk yorumu, doğrulanmamış). |

İlgili kurallar: R01, R02, R04, R05, R06, R07, R08, R09, R10, R11, R12, C2, C8

## Entity geçmişi ve velocity feature'ları

| Feature | Anlamı |
|---|---|
| ent_txn_count | Entity'nin bu işlemden önceki işlem sayısı. Trusted tanımında fit q90 (809) üzeri "uzun geçmiş" sayılır. |
| ent_age_days | Entity'nin ilk işleminden bu işleme kadar geçen gün. |
| ent_cnt_1h | Entity'nin son 1 saatteki önceki işlem sayısı (24 saatlik ve 7 günlük karşılıkları da vardır). |
| small_amt_streak_1h | Entity'nin son 1 saatteki önceki küçük tutarlı (<= fit q10) işlem sayısı. Card testing sinyalidir. |
| is_first_seen | Entity'nin ilk işlemiyse 1. |
| ent_daily_avg | Entity'nin geçmiş günlük ortalama işlem sayısı: ent_txn_count / max(ent_age_days, 1). |
| burst_ratio_1h | ent_cnt_1h / ent_daily_avg. 3'ten büyükse son saat entity'nin kendi ritminin 3 katından fazladır (R03). 24 saatlik karşılığı burst_ratio_24h C5'te kullanılır. |

İlgili kurallar: R01, R03, R06, R07, R10, C1, C3, C4, C5

## Kart ve cihaz feature'ları

| Feature | Anlamı |
|---|---|
| card_age_days | Kart yaşı: D1 sütunu (kartın ilk kullanımından bu yana gün). D1 = kart yaşı bir yorumdur. 0 yeni kart demektir. |
| device_ent_match | Entity'nin bu cihazı daha önce kullanıp kullanmadığını gösteren geçmiş sayacı. |
| known_device | device_ent_match >= 1 ise 1: cihaz entity tarafından daha önce kullanılmış. |
| known_email | Entity bu P_emaildomain değerini daha önce bir işlemde kullandıysa 1 (boş e-posta hiç bilinen sayılmaz). |
| has_identity | İşlemin identity (cihaz/kimlik) kaydı varsa 1. ProductCD = W için identity kaydı hiç yoktur. |

İlgili kurallar: R04, R08, R10, R12, C4, C8

## Coğrafya ve e-posta feature'ları

| Feature | Anlamı |
|---|---|
| addr2 | Fatura ülke kodu. Baskın değer 87 ABD kabul edilir (topluluk yorumu, varsayım). |
| foreign_addr2 | addr2 dolu ve fit kümesindeki baskın değerden farklıysa 1. |
| addr2_missing | addr2 boşsa 1. |
| email_mismatch | Alıcı (P) ve gönderen (R) e-posta alanı ikisi de doluysa ve farklıysa 1. Satırların yaklaşık %21'inde her ikisi de dolu olabilir. |
| ProductCD | Ürün kodu. W ana akım üründür; C azınlık, çoğunlukla ülkesiz ve identity kayıtlı dijital kanaldır. |

İlgili kurallar: R02, R05, R08, R09, R11, C6a, C6b, C9a, C9b

## Zaman feature'ları

| Feature | Anlamı |
|---|---|
| TransactionDT | Saniye cinsinden zaman ofseti. Varsayım: gerçek zaman = 2017-12-01 00:00:00 + TransactionDT. |
| local_hour_est | Tahmini yerel saat: (saat - 6) mod 24. Saat dilimi veride yoktur, düşük hacimli 6 saat yerel 00-06 kabul edilir. |
| is_low_volume_window | Fit kümesinde hacmin en düşük olduğu ardışık 6 saatlik pencerede ise 1 (tahmini yerel 00-06). |
| is_weekend | Referans tarihe göre hafta sonu ise 1 (yerel takvime göre değil). |
| holiday_season | Fit hacminden öğrenilen tatil sezonu penceresinde (2017-12-19 ile 2017-12-26) ise 1. |

İlgili kurallar: R02, R12, C1, C2, C3, C7

## Skor alanları

| Alan | Anlamı |
|---|---|
| anomaly_score | Dört anomali katmanının (multivariate 0,35, entity 0,25, column 0,20, temporal 0,20) ağırlıklı ortalamasının fit kuantil tablosuyla [0,1]'e normalleştirilmiş hali. |
| adjusted_score | Context düzeltmesi sonrası skor, [0,1]'e kırpılmış (çıktı için). |
| adjusted_score_unclipped | Kırpılmamış düzeltilmiş skor; alarm sıralaması ve skor inceleme eşiği bunu kullanır. |
| final_score | Kural boost'ları eklendikten sonraki skor, [0,1]'e kırpılmış. |
| dominant_layer | Skora en büyük ağırlıklı katkıyı veren anomali katmanı (C7 koşulunda kullanılır). |
| decision_source | Kararı veren kaynak: kural kimliği, `score` veya `default`. |

İlgili kurallar: C5, C7, R10
