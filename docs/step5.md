# Adım 5 - Skor normalizasyonu ve birleştirme

**isFraud kullanıldı mı: hayır - yalnızca evaluation'da raporlama.** Normalizasyon tabloları ve ağırlıklar etiketsizdir. Ağırlıklar (`configs/weights.yaml`) elle seçildi ve holdout metriklerine bakılarak değiştirilmedi. Metrikler `src/evaluation/metrics.py` ile yalnızca raporlanır.

## Normalizasyon (K-16)
`QuantileNormalizer` (src/detection/normalization.py): fit satırlarındaki ham skorun 1001 noktalı kuantil tablosu; eşit değerler ortalama rank alır; `np.interp`, [0,1]'e kırpılır. Neden rank tabanlı: ham ölçekler farklı (IF 0-1, ECDF `-log10 p`), rank dağılım şeklinden bağımsız ve katmanları karşılaştırılabilir yapar. Tablolar `artifacts/detectors/normalization_table.parquet` (layer, level, raw_value) ve her detector joblib'inde; ham ve normalize skor ikisi de saklanır. Fit dışı uç değerler 0/1'de doyar.

## Birleştirme (K-17)
`WeightedAverage` (src/scoring/aggregation.py, `Aggregator` arayüzü): `raw_anomaly_score = 0,35*multivariate + 0,25*entity + 0,20*column + 0,20*temporal`, toplam 1 (yüklemede kontrol). `contrib_<katman> = w*skor` sütunları toplamı `raw_anomaly_score`'dur. Katman çıkarıldığında kalan ağırlıklar yeniden normalize edilir (ablation). `anomaly_score_norm`: aynı toplamın kendi fit kuantil tablosuyla normalizesi (monoton; eşiklerin fit yüzdeliği olarak okunması için).

Neden ağırlıklı ortalama: yorumlanabilir, ağırlık config'te değiştirilebilir, katkı satır bazında görülür. Alternatifler yalnızca karşılaştırma tablosunda: B (ağırlık ~ 1/ort. |Spearman| diğer katmanlarla; fit'ten), max (tek gürültülü katmana duyarlı), noisy-OR (hızla doyar). Ağırlık gerekçesi `configs/weights.yaml` içinde.

## Servis
`ScoringService` (src/scoring/service.py): `fit` (4 katman + toplam normalizer, yalnızca fit kümesi), `score_batch(df)`, `score_one(features: dict) -> ScoreResult` (aynı kod; açıklamalar katman bazlı), `save`/`load` (`artifacts/detectors`). `Container.scoring_service` (Singleton, yalnızca yükler; API eğitim yapmaz). `ScoreResult.raw_score` = `raw_anomaly_score`, `ScoreResult.score` = `anomaly_score_norm`.

## Çıktılar
| Dosya | Şema |
|---|---|
| `reports/scores/raw_score.parquet` | index TransactionID; `raw_anomaly_score`, `anomaly_score_norm`, `contrib_multivariate`, `contrib_entity`, `contrib_column`, `contrib_temporal` |
| `reports/scores/layer_scores.parquet` | Adım 4 |
| `reports/scores/holdout_metrics.csv`, `ablation.csv`, `corr_weights.csv`, `holdout_base.csv` | değerlendirme (yalnızca raporlama) |
| `artifacts/detectors/` | detector joblib'leri, `scoring_meta.joblib`, `normalization_table.parquet` |

## Holdout sonuçları (TAM veri; fit 472.432, holdout 118.108 satır, 4.064 pozitif, taban oranı %3,44)
| Kapsam | PR-AUC | ROC-AUC | recall@%1 | recall@%5 |
|---|---|---|---|---|
| multivariate | 0,088 | 0,695 | 0,038 | 0,197 |
| entity | 0,047 | 0,577 | 0,012 | 0,088 |
| column | 0,057 | 0,621 | 0,029 | 0,125 |
| temporal | 0,046 | 0,598 | 0,001 | 0,070 |
| **birleşik (ağırlıklı ort.)** | 0,081 | 0,683 | 0,046 | 0,168 |

Ablation (aynı holdout):
| Grup | Varyant | PR-AUC | ROC-AUC | recall@%1 | recall@%5 |
|---|---|---|---|---|---|
| leave one out | multivariate'siz | 0,061 | 0,642 | 0,030 | 0,134 |
| leave one out | entity'siz | 0,074 | 0,687 | 0,029 | 0,158 |
| leave one out | column'suz | 0,082 | 0,690 | 0,048 | 0,166 |
| leave one out | temporal'siz | 0,082 | 0,671 | 0,046 | 0,184 |
| variant | IF-full (V dahil) | 0,091 | 0,722 | 0,049 | 0,173 |
| aggregator | B: korelasyon ağırlıklı | 0,068 | 0,667 | 0,042 | 0,128 |
| aggregator | max | 0,056 | 0,645 | 0,008 | 0,104 |
| aggregator | noisy-OR | 0,069 | 0,668 | 0,024 | 0,147 |

B ağırlıkları (fit): multivariate 0,159, entity 0,201, column 0,166, temporal 0,475.

Yorum (sınırlı): sinyal zayıf, farklar küçük. En iyi tek katman multivariate; birleşik skor recall@%1'de en iyi tek katmandan yüksek (0,046 vs 0,038), PR-AUC, ROC-AUC ve recall@%5'te multivariate'in altında. Ablation'da multivariate çıkarılınca düşüş en büyük (PR-AUC 0,081 -> 0,061); entity çıkarılınca da düşüş var; column ve temporal çıkarılınca birleşik değişmiyor. IF-full birleşik skorun üstünde ama V kolonları yorumlanamaz, ana skora alınmadı (K-13). Max ve noisy-OR (ve B) ağırlıklı ortalamadan düşük. Bu sonuçlarla yöntem ve ağırlık DEĞİŞTİRİLMEDİ (etiketle ayar yasak).

Örneklem koşusu (SAMPLE_N=50000, 10.000 holdout, 228 pozitif) yalnızca duman testidir: birleşik PR-AUC 0,050, ROC-AUC 0,635, recall@%1 0,053, recall@%5 0,140.

## Adım 6'ya girdi: temporal katman bulgusu
Temporal katmanın holdout recall@%1 değeri 0,001'dir (taban oranın çok altı; PR-AUC 0,046, ROC-AUC 0,598). Temporal skorun en yüksek %1'lik dilimi sıradan işlemleri öne çıkarıyor olabilir; Adım 6 (context adjust) bu katmanın katkısını (`contrib_temporal`) ayrıca gözden geçirmelidir. Kullanıcı kararı: ağırlıklar (0,35 / 0,25 / 0,20 / 0,20) ve IF-core holdout sonucuna göre DEĞİŞTİRİLMEDİ; bulgu bir sınır olarak kayıtlıdır. Üst %1 diliminin profili (review raporu, `reports/reviews/step4_5_review.md`): 1.181 işlemin 1.138'i (%96,4) tek bir entity'ye ait (card1 15775, addr1 330); bu entity'nin ProductCD=S oranı %96,5 (tüm holdout'ta %3,0). Üst dilimde 34 farklı entity var, `ent_txn_count` medyanı 821 (tüm holdout 116), `is_first_seen` oranı 0. Baskın alt skor velocity (satırların %97'sinde, ortalama 5,50, teorik tavan 5,67: doygun). Entity'nin 1.453 işleminin yalnızca 37'si fit'te, 1.416'sı holdout'ta; medyan `ent_cnt_1h` 66, fit p99.9 ise 12. Yorum: katman, fit'te neredeyse hiç görülmemiş tek bir yüksek hacimli entity'nin burst'ünü yakalıyor; recall@%1 = 0,001 bu tek davranışı ölçer, katmanın genel gücünü değil. Kullanıcı kararı: tasarım değişmez; Adım 6 context kuralları bu burst'ü (ör. ProductCD=S, tek entity'de yoğunlaşan velocity) sönümleme adayı olarak ele alabilir. Bulgu `docs/assumptions.md` entity = kart grubu varsayımına kanıt olarak da eklendi.

## Bilinen sınırlar
- Temporal üst %1 tek bir entity'nin burst'üdür (yukarıdaki bölüm); velocity bu entity'de doygundur ve temporal metrikleri tek bir davranış belirler.
- Aggregate dağılımı toplama nedeniyle merkezde yoğunlaşır (std 0,20); eşik için `anomaly_score_norm` kullanın.
- Fit dışı uç skorlar 1'de doyar, sıra bilgisi kaybolur.
- Temporal katman online için `HourStore` durumuna bağlıdır (artifact; canlı güncelleme sonraki adımların kararı).
- `ProductCD` sinyali yok (features.parquet'te yok).

## Bir sonraki adımın girdisi (K-19)
Adım 6 ve sonrası `reports/scores/raw_score.parquet` içindeki `anomaly_score_norm` sütununu okur (eşik, bant ve kural karşılaştırmaları bu skor üzerinden); `raw_anomaly_score` ham toplam olarak ve denetim için durur, `contrib_*` açıklama içindir.

## Komutlar
Örneklem: `SAMPLE_N=50000 python scripts/run_scoring.py`. Tam veri: `python scripts/run_scoring.py` veya `make score` (önce `make features`); tam veri ~90 sn, tepe bellek ~3 GB. `--no-eval` değerlendirmeyi atlar.
