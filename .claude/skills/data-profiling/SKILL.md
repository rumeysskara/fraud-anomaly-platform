---
name: data-profiling
description: "Adım 1-2. IEEE-CIS transaction ve identity dosyalarını birleştirirken, eksik veri, kolon tipi, veri kalitesi, cardinality, outlier, distribution, rare category ve entity davranış analizi yaparken kullan."
---

# Data Loading, Profiling & Schema Intelligence

## Girdi
- data/raw/train_transaction.csv, data/raw/train_identity.csv (TransactionID ile ilişkili)

## Çıktı
- data/processed/merged.parquet (downcast edilmiş, birleşik veri)
- reports/profile/column_schema.parquet: kolon, inferred_type (numeric|categorical|datetime|id|flag), null_ratio, n_unique, cardinality_class
- reports/profile/missing.parquet, outliers.parquet, distributions.parquet,
  rare_categories.parquet, column_relations.parquet, entity_patterns.parquet
- docs/step1-2.md (şema + bulgular + bir sonraki adımın girdisi)

## Adım 1: Yükleme ve hazırlık
0. Adım 0'da yazılan `src/data/loader.py`'yi kullan/genişlet; önce `SAMPLE_N=50000` ile, sonra tam veriyle çalıştır.
1. Dosyaları chunk'sız ama dtype kontrollü oku; float64 -> float32, int -> en küçük tip, düşük cardinality string -> category.
2. LEFT JOIN: transaction ana tablo, identity TransactionID ile eklenir. Identity kaydı olmayan satırlar kalır; `has_identity` flag'i üret.
3. Join sonrası satır sayısı, eşleşme oranı, duplicate TransactionID kontrolü logla.
4. Eksik veri: kolon bazında null oranı, kolon grupları (V1-V339, C, D, M, id_*) için grup bazlı özet.
5. Kolon tipi otomatik belirleme (kural tabanlı, isimle hardcode etme):
   - object/category -> categorical; çok az unique sayısal -> categorical/flag
   - TransactionDT -> datetime-benzeri (referans noktası farkı; sabit başlangıç tarihi varsay ve belirt)
   - *ID/ id_* tarzı yüksek unique -> id
6. Veri kalitesi: sabit kolonlar, %90+ null kolonlar, duplicate satırlar, aralık dışı değerler (negatif tutar vb.).
7. Yüksek cardinality tespiti: n_unique / n_rows ve mutlak eşik (örn. >1000) ile işaretle. card1, addr1, DeviceInfo, id_30-33, email domain'leri beklenen adaylar.

## Adım 2: Profiling ve semantik yapı
1. Numeric / categorical / datetime ayrımını şemada kalıcılaştır.
2. Outlier: IQR ve robust z-score (median/MAD); TransactionAmt için log ölçeğinde de bak.
3. Distribution: skewness, kurtosis, quantile tablosu; kategorikler için top-N frekans.
4. Rare categorical combination: örn. (card4, card6, ProductCD), (P_emaildomain, R_emaildomain), (DeviceType, DeviceInfo) çiftlerinde frekansı çok düşük kombinasyonlar.
5. Kolon ilişkileri: numeric için Spearman, kategorik için Cramér's V; yüksek korelasyonlu V-kolon kümelerini belirle (redundancy).
6. Entity davranış: aday proxy anahtarları (card1, card1+card2+addr1 vb.) için işlem sayısı dağılımı, kaç entity'nin tek işlemli olduğu, tutar varyansı. Proxy seçimini rakamlarla gerekçelendir (karar feature-engineering skill'inde kullanılır).

## Görseller
Teknik dokümana girecek birkaç grafik `reports/figures/` altına PNG: null oranı (kolon grubu bazlı),
TransactionAmt log dağılımı, saatlik işlem hacmi, entity başına işlem sayısı dağılımı.

## Kurallar
- `isFraud` yalnızca ayrı bir Series olarak tutulur; profiling raporlarında dağılım olarak gösterilebilir ama feature'lara karışmaz.
- Tüm çıktılar tekrar üretilebilir script ile (scripts/run_profiling.py), seed=42.

## Kontrol listesi
- [ ] Birleşik parquet var, satır sayısı = transaction satır sayısı
- [ ] column_schema her kolon için tip + null_ratio + cardinality_class içeriyor
- [ ] Yüksek cardinality listesi dokümanda
- [ ] Entity proxy önerisi sayısal gerekçeyle yazılmış
- [ ] Testler küçük sentetik veriyle geçiyor
- [ ] docs/step1-2.md yazıldı
