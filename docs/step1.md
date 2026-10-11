# Adım 1 — Yükleme, birleştirme ve veri kalitesi

## Ne yapıldı
- `train_transaction.csv` (590.540 satır) ana tablo, `train_identity.csv` (144.233 satır) `TransactionID` ile LEFT JOIN edildi.
  Eşleşme: 144.233 satır (%24,4). Identity kaydı olmayan satırlar korunur; `has_identity` bayrağı üretildi.
  Join sonrası satır sayısı 590.540 (transaction ile aynı), tekrar eden `TransactionID` yok (iki dosyada da 0).
- `src/data/loader.py` tek yükleme yoluna indirildi: `load_merged` (chunk'lı okuma, her chunk'ta float64 -> float32 ve int downcast,
  düşük cardinality string -> `category`, join istatistikleri) ve onu saran `load_data(data_dir, sample_n, settings) -> (X, y)`.
  Dış imza ve davranış (index = TransactionID, TransactionDT'ye göre sıralı, `isFraud` yok, `sample_n` = nrows) aynı; tek fark
  `load_data` çıktısına artık `has_identity` kolonu ve `category` dtype'ları da geliyor. Etiket ayrı `y` Series'i olarak döner.
  Chunk boyutu ve category oranı `configs/profiling.yaml` (`loading`) içinde.
- Çıktı: `data/processed/merged.parquet` (TransactionID index, 433 kolon, `isFraud` yok, ~81 MB, bellekte ~967 MB).
  `SAMPLE_N` verilirse çıktılar `merged_sample.parquet` ve `reports/profile/sample/` altına gider; tam veri çıktıları ezilmez.
- Zaman: `TransactionDT` saniye ofseti; datetime = 2017-12-01 00:00:00 + TransactionDT (**varsayım**, `configs/settings.yaml`).
  Veri ~183 günü kapsar. Split: ilk %80 (472.432 satır) fit, son %20 (118.108) holdout.

## Çalıştırma süresi ve bellek (MacBook Air, 16 GB)
| Çalışma | Süre | Tepe RSS (`/usr/bin/time -l`) |
|---|---|---|
| `SAMPLE_N=50000` | ~26 s | ~1,5 GB |
| Tam veri (`scripts/run_profiling.py`, tüm adımlar) | ~82 s | ~3,5 GB (peak footprint 5,3 GB) |
| Yalnızca yükleme aşaması (`load_merged`) | ~13 s | ~1,8-2,0 GB |
| Eski tek-parça `load_data` (kaldırıldı; karşılaştırma için ölçülmüştü) | ~12 s | ~2,6 GB |

Bellek sorunu çıkmadı. `load_merged` yükleme tepesini ~%30 düşürür ve string kolonları `category` yapar;
profil aşamasının tepesi (3,5 GB) Spearman için alınan 100k satırlık rank matrisinden ve kolon bazlı kopyalardan gelir.

## Veri kalitesi bulguları (tam veri)
- Eksik veri grup bazlı (`reports/profile/group_missing.csv`): id %85, dist %77, D %58, M %50, V %43, addr %11, card %0,5, C %0.
  V kolonları 15 eksiklik bloğuna ayrılır (aynı null sayısına sahip kolonlar birlikte eksik; `missing.parquet` -> `null_block`).
- %90+ null kolonlar (12): dist2, D7, id_07, id_08, id_18, id_21, id_22, id_23, id_24, id_25, id_26, id_27.
- Sabit kolon: tam veride yok (50k örneklemde M1 ve V107 sabit görünür; örneklem yanıltabilir).
- Tekrarlı satır: 3 (TransactionID dışındaki tüm kolonlar aynı); önemsiz, silinmedi.
- Aralık dışı: `TransactionAmt` <= 0 yok. D kolonlarında negatif değer var: D4 (15), D6 (3), D11 (7), D12 (2), D14 (3), D15 (15) satır.
- Kolon tipleri (kural tabanlı): numeric 301, categorical 105, flag 26, id 1 (TransactionID), datetime 1 (TransactionDT).
- **Yüksek cardinality (>1000 benzersiz ve categorical/id)**: `card1` (13.553), `DeviceInfo` (1.786), `TransactionID`.
  Orta ama frekans kodlaması önerilenler: `card2` (500), `addr1` (332), `id_33` (260), `id_31` (130), `card5` (119), `card3` (114), `id_30` (75), `addr2` (74), `P_emaildomain` (59), `R_emaildomain` (60).
- `ProductCD = W` olan 439.670 satırın hiçbirinde identity kaydı yok; `has_identity` ile Cramér's V = 0,97. Identity özellikleri
  W ürününde yapısal olarak eksiktir (tesadüfi eksiklik değil).

## Kolon şeması (`reports/profile/column_schema.parquet|csv`)
`column, group, dtype, inferred_type (numeric|categorical|datetime|id|flag), type_source (rule|dictionary|config),
null_ratio, n_unique, unique_ratio, cardinality_class (constant<=1 | low<=20 | medium<=1000 | high), is_high_cardinality`.
Tipler veriye bakan kurallarla belirlenir (<=2 benzersiz = flag; tamsayı ve <=10 benzersiz = categorical; tamsayı ve benzersiz
oranı >0,9 ve >1000 = id). Tek isim tabanlı istisna: `card*` ve `addr*` grupları sayısal kodlu kategoriktir (IEEE-CIS veri sözlüğü);
bunlar `type_source=dictionary` ile işaretlenir. Not: `id` kuralı örnekleme duyarlıdır (50k örneklemde id_02 `id` çıkar, tam veride çıkmaz).

## isFraud kullanımı
Kullanıldı mı: **hayır** (özellik, eşik, entity ve kolon seçiminde). `isFraud` yalnızca loader'dan ayrı `y` olarak geldi ve
tek bir yerde okundu: fit/holdout taban oranı raporlamak için (fit %3,51; holdout %3,44), hiçbir seçimde kullanılmadı.

## Bir sonraki adımın girdisi
`data/processed/merged.parquet` + `reports/profile/column_schema.parquet` (tip ve cardinality sınıfı). Adım 3 bunları okuyup
frequency/count encoding ve geçmişten hesaplanan zamansal özellikleri üretir.

## Bilinen sınırlar
- Tüm profiling eşikleri ve sabitleri (cardinality sınıfları, %90 null, IQR 1,5, robust z, rare oranı 1e-4, küme eşiği 0,95, örnek boyutu,
  entity adayları vb.) tek kaynak olan `configs/profiling.yaml` içinde; kod yalnızca oradan okur (`src/profiling/config.py`).
- Referans tarih bir varsayımdır; saat/gün özellikleri göreli yorumlanmalıdır.
- 3 tekrarlı satır ve D negatifleri düzeltilmedi, yalnızca raporlandı.
