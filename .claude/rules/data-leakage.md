# Veri Sızıntısı (Leakage) Kuralları

- `isFraud` kolonu feature üretiminde, anomali modellerinde, skor ağırlıklarında,
  context kurallarında ve rule engine koşullarında KULLANILMAZ.
- `isFraud` yalnızca `src/data/loader.py` (ayrı `y` olarak döndürmek için) ve `src/evaluation/` içinde geçer:
  PR-AUC, ROC-AUC, recall@k, precision@k, "önce/sonra false positive" karşılaştırması.
- Yükleme katmanında etiket ayrı bir Series olarak tutulur (`y`), feature DataFrame'ine girmez.
- Zamansal özellikler (user_avg_amount, velocity, count) yalnızca GEÇMİŞ işlemlerden
  hesaplanır: `TransactionDT` sırasına göre expanding/rolling, mevcut ve gelecek satırlar
  hesaba katılmaz (shift(1) veya closed='left').
- Zaman bazlı split: TransactionDT'ye göre ilk %80 fit, son %20 holdout. Rastgele split yasak.
- Fit/score ayrımı: istatistik (ortalama, std, frekans) önce fit kümesinden öğrenilir,
  sonra uygulanır. Tüm veri üzerinden hesaplanıp geri yazılmaz.
- Unsupervised yaklaşım korunur: etiket kullanılarak ağırlık/eşik ayarlanmaz.
  Ağırlıklar elle veya veri varyansı gibi etiketsiz bir ölçütle seçilir ve gerekçelendirilir.
- Her adımın dokümanında "isFraud kullanıldı mı: hayır" notu yer alır.
