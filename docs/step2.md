# Adım 2 — Profiling ve semantik yapı

Eşikler ve entity adayları `configs/profiling.yaml` içindedir (kodda ikinci kopya yok). Kod: `src/profiling/` (schema, quality, distributions, relations, entity, figures, report), betik: `scripts/run_profiling.py`
(`make profile` -> `run_pipeline.py --only profile`). Tüm tablolar `reports/profile/` altında (parquet; küçük olanlar ayrıca csv),
özet `reports/profile/summary.md`, grafikler `reports/figures/*.png`. Seed 42.

## Çıktılar
| Dosya | İçerik |
|---|---|
| `outliers.parquet` | Sayısal kolon başına IQR çitleri ve robust z (median/MAD, 0,6745 ölçeği, eşik 3,5) aykırı sayıları; `TransactionAmt__log1p` ayrı satır |
| `distributions.parquet` | count, mean, std, min/max, skew, kurtosis, q01..q99 |
| `categorical_topn.parquet` | Kategorik kolonlarda ilk 10 değer ve oranı |
| `rare_categories.parquet`, `rare_summary.csv` | Seyrek kombinasyonlar (oran < 1e-4; NaN ayrı değer). Çiftler: (card4,card6,ProductCD), (P_emaildomain,R_emaildomain), (DeviceType,DeviceInfo) + tek kolonlar |
| `column_relations.parquet` | Spearman (|rho|>=0,8) ve Cramér's V (>=0,5, bias düzeltmeli) çiftleri |
| `redundancy_clusters.parquet|csv` | Aynı grupta |rho|>=0,95 bağlı bileşenler, temsilci = en az null'lu kolon |
| `entity_patterns.parquet|csv` | Entity adayları karşılaştırması (aşağıda; 10 aday, her biri `full` ve `fit`) |
| `d1n_constancy.parquet|csv` | D1n sabitlik kontrolü (aşağıda) |
| `temporal.parquet` | Saat/haftanın günü dağılımı |

## Bulgular (tam veri)
- **TransactionAmt**: medyan 68,8; ortalama 135; skew 14,4; kurtosis 1124; max 31.937. Ham ölçekte IQR ile %11,3 aykırı,
  log1p ölçekte %3,5 (robust z: %10,1 -> %1,2). Dağılım log ölçekte neredeyse simetrik; aykırılık büyük ölçüde çarpıklık etkisidir.
  En çarpık kolonlar V311, V129, V309, V206 (skew 180-320).
- **V kolonları**: 339 kolonun 222'si 71 kümeye düşüyor (|rho|>=0,95); küme başına temsilci tutulursa 339 -> 188. C'de 1 (C8,C10),
  D'de 3 küme (örn. D4-D6-D12). Bu, Adım 3'te V için kolon azaltma girdisidir.
- **Cramér's V** yüksek çiftler: ProductCD-has_identity 0,97 (W'de identity yok), id_28-id_29 0,98, id_15-id_16 0,98.
- **Seyrek kombinasyon**: (DeviceType,DeviceInfo) 1.943 kombinasyonun %94'ü seyrek (satırların %2,4'ü); (P,R emaildomain) 743 kombinasyonun
  %81'i seyrek (satırların %0,87); (card4,card6,ProductCD) satırların %0,03'ü. Seyrek kombinasyon Adım 4'te "nadir görülme" sinyali adayıdır.
- **Zamansal**: işlem hacmi saat 7-9'da dip (%0,4-0,6/saat), 17-22 arası tepe (~%7/saat). Saat dilimi bilinmediği için mutlak
  saat yorumlanmaz, yalnızca döngü biçimi kullanılabilir.

## Entity proxy karşılaştırması (etiketsiz; tam veri ve fit kümesi)
Tam tablo: `reports/profile/entity_patterns.csv` (her aday için `full` ve `fit` satırı). Tam veri özeti:

| Aday | Tanımsız satır | Entity sayısı | Tek işlemli entity | Tek işlemli satır payı | İşlem/entity medyan / p90 / p99 / max | Geçmişi olan satır | Holdout'ta fit'te görülen | İçi/genel log-tutar std |
|---|---|---|---|---|---|---|---|---|
| A card1 | %0 | 13.553 | %25,4 | %0,6 | 4 / 46 / 786 / 14.932 | %97,7 | %98,9 | 0,65 / 0,94 |
| B card1+addr1 | %11,1 | 37.531 | %39,5 | %2,8 | 2 / 23 / 194 / 5.885 | %92,8 | %95,7 | 0,60 / 0,89 |
| C card1+card2+card3+card5+addr1 | %12,9 | 38.145 | %39,4 | %2,9 | 2 / 22 / 188 / 5.866 | %92,6 | %95,6 | 0,59 / 0,89 |
| D card1..card6 (addr yok) | %1,9 | 13.691 | %25,5 | %0,6 | 4 / 45 / 728 / 14.112 | %97,6 | %98,9 | 0,65 / 0,94 |
| E card1+addr1+P_emaildomain | %26,7 | 73.407 | %49,7 | %8,4 | 2 / 10 / 69 / 2.242 | %83,0 | %87,2 | 0,51 / 0,89 |
| F card1+addr1+DeviceInfo | %86,8 | 31.576 | %66,6 | %26,9 | 1 / 4 / 23 / 1.309 | %59,6 | %66,3 | 0,39 / 0,83 |
| G card1+P_emaildomain | %16,0 | 38.162 | %41,5 | %3,2 | 2 / 17 / 187 / 7.041 | %92,3 | %94,7 | 0,56 / 0,95 |
| H card1+addr1 (addr1 NaN ayrı seviye) | %0 | 39.974 | %39,4 | %2,7 | 2 / 22 / 201 / 9.928 | %93,2 | %95,8 | 0,59 / 0,94 |

"Geçmişi olan satır" = aynı entity'den daha önce işlemi bulunan satırların payı (zamana göre sıralı); geçmişten hesaplanan
özelliklerin (velocity, user_avg_amount) kaç satırda dolu olacağını gösterir. Fit kümesindeki değerler benzerdir (örn. A: 12.730 entity).

Gözlemler: (1) card2/card3/card4/card5/card6 eklemek entity sayısını neredeyse değiştirmiyor (A->D: +138; B->C: +614) ama tanımsız
satırı artırıyor. (2) addr1 eklemek entity sayısını ~2,8 katına çıkarıyor, tutar varyansı düşüyor ama %11 satır tanımsız kalıyor; NaN'ı ayrı seviye
yapmak (H) bunu sıfırlıyor. (3) card1 tek başına geniş: p99 = 786 işlem, max 14.932 (birden çok kart sahibini birleştiriyor olabilir).
(4) E ve F tanımsız satır veya geçmiş yetersizliği nedeniyle zayıf; DeviceInfo yalnızca ek sinyal olabilir.

## Ek adaylar: D1n içeren entity'ler (I, J)
D1n = floor(TransactionDT / 86400) - D1 (kartın yaklaşık ilk kullanım günü; D1 yalnızca TransactionDT'den türetilen bir süre, etiketle ilgisi yok).
D1 tam veride tamsayı değerli (%100) ve %0,2 NaN; NaN ayrı seviye. Tüm NaN'lar I ve J'de ayrı seviyedir (tanımsız satır %0).

| Aday | Entity | Tek işlemli entity | Tek işlemli satır payı | İşlem/entity min / medyan / p75 / p90 / p99 / max | Geçmişi olan satır | Holdout'ta fit'te görülen | İçi/genel log-tutar std | Medyan aktif gün |
|---|---|---|---|---|---|---|---|---|
| A card1 | 13.553 | %25,4 | %0,6 | 1 / 4 / 14 / 46 / 786 / 14.932 | %97,7 | %98,9 | 0,65 / 0,94 | 133 |
| H card1+addr1 (NaN seviye) | 39.974 | %39,4 | %2,7 | 1 / 2 / 7 / 22 / 201 / 9.928 | %93,2 | %95,8 | 0,59 / 0,94 | 108 |
| I card1+addr1+D1n | 217.850 | %57,5 | %21,2 | 1 / 1 / 3 / 6 / 20 / 1.414 | %63,1 | %43,5 | 0,35 / 0,94 | 15 |
| J card1+addr1+P_emaildomain+D1n | 273.919 | %64,8 | %30,1 | 1 / 1 / 2 / 4 / 15 / 1.414 | %53,6 | %39,9 | 0,29 / 0,94 | 16 |

Fit kümesi değerleri `entity_patterns.csv` içinde (örn. I: 182.535 entity, p99 19, max 361).

### D1n sabitlik kontrolü (`reports/profile/d1n_constancy.csv`)
Soru: aynı entity içinde D1n sabit mi (±1 gün tolerans)? D1n'i içermeyen H (card1+addr1) entity'lerinde D1 tanımlı satırlar için:

| Entity | D1n tek değer | D1n birkaç değer ama aralık <= 1 gün | D1n aralığı > 1 gün | Aralık > 1 olanların medyan aralığı |
|---|---|---|---|---|
| H (tüm entity'ler) | %53,8 entity / %6,5 işlem | %0,25 entity / %0,05 işlem | %46,0 entity / %93,4 işlem | 161 gün |
| H (>= 2 işlemli entity'ler) | %23,7 entity / %3,9 işlem | %0,41 entity / %0,05 işlem | %75,9 entity / %96,0 işlem | 161 gün |
| REF: card1..card6+addr1 (sıkı "aynı kart" anahtarı), >= 2 işlemli | %24,1 / %4,2 | %0,44 / %0,05 | %75,5 / %95,8 | 160 gün |

- I entity'lerinde D1n aralığı (max-min) <= 1 olan pay %100'dür (entity ve işlem), ama bu anlamsız bir doğrulamadır: D1n anahtarın parçası olduğu için
  aralık tanım gereği 0'dır.
- Anlamlı olan sonuç H'dedir: işlemlerin %96'sı D1n'in gün bazında değiştiği (medyan 161 gün) entity'lerde. Yani card1+addr1 birden çok kartı
  (farklı ilk kullanım günü) birleştiriyor; D1n bu birleşmeyi ayırır. Aralık <= 1 olan "jitter" grubu çok küçük (99 entity): D1n farklıysa genellikle
  ±1 gün değil, büyük farkla farklı. Yani D1n gürültülü değil, ayırt edici. Daha sıkı kart anahtarı (REF) da aynı sonucu veriyor, yani birleşme yalnızca
  card2..card6 ile giderilemiyor.
- Yorum sınırı: "D1n farklı = farklı kart" varsayımı bu analizle kanıtlanamaz (etiket yok, gerçek kart no yok). Alternatif açıklama D1'in her
  kartta gerçekten ilk kullanım günü olmamasıdır. Destekleyen ipucu: I entity'lerinin içi tutar std'si 0,35 (H: 0,59), yani I daha homojen.

## A, H, I, J karşılaştırması ve öneri (karar kullanıcıda)
| Aday | Artı | Eksi |
|---|---|---|
| A card1 | Tanımsız satır yok; geçmişi olan satır %97,7; holdout'ta görülme %98,9 (fit'te öğrenilen istatistik neredeyse her satıra uygulanır); en basit | Birden çok kartı birleştiriyor: p99 786, max 14.932; içi tutar std 0,65 (en gevşek) |
| H card1+addr1 | Tanımsız satır yok; geçmiş %93,2; holdout görülme %95,8; A'dan ince (medyan 2, p99 201), tutar std 0,59 | addr1 NaN seviyesi büyük bir torba (max 9.928); hâlâ birden çok kart birleşir (D1n kontrolü) |
| I +D1n | En homojen tek-kart yaklaşımına yakın (tutar std 0,35, p99 20); entity içi davranış daha "kişisel" | Holdout satırlarının yalnızca %43,5'inin entity'si fit'te görülmüş: fit'te öğrenilen entity istatistiği satırların %56'sında soğuk başlangıç; yalnızca %63 satırın geçmişi var; %21 satır tek işlemli entity'de; D1 NaN ve D1'in anlamı varsayımsal; medyan aktif süre 15 gün |
| J +P_emaildomain | En ince; tutar std 0,29 | I'nin tüm eksileri daha ağır: holdout görülme %39,9, geçmiş %53,6, tek işlemli satır %30,1 |

Öneri: **H**, entity istatistikleri (fit'te öğren, holdout'ta uygula) için birincil proxy. Gerekçe: holdout'ta %95,8 kapsama ve %93 geçmiş,
I/J'de ise kapsama yarıya düşüyor. D1n, entity anahtarına katılmak yerine ikincil bir sinyal olarak (örn. "kart yaşı" = işlem günü - D1, ya da
H içinde D1n ile ayrıştırılmış alt-entity'ye ancak görüldüyse düşme, görülmediyse H'ye geri düşme) kullanılabilir. I yalnızca bu
hiyerarşik geri düşüşle anlamlıdır. Seçim kullanıcıdadır; `configs/entity.yaml` ve `docs/decisions.md` bu adımda yazılmadı.

## Entity kararı (bekliyor)
Önceki bölümde A-J seçenekleri ve öneri var; karar ana oturumda kullanıcıya sorulacak.

## isFraud kullanımı
Kullanıldı mı: **hayır**. Entity karşılaştırması, outlier, ilişki ve seyreklik analizleri etiketsizdir. `y` yalnızca fit/holdout
taban oranını raporlamak için okundu (bkz. step1.md).

## Bir sonraki adımın girdisi
`reports/profile/entity_patterns.csv` (entity kararı için), `redundancy_clusters.csv` (V azaltma), `column_schema.parquet`,
`rare_summary.csv` (nadirlik özelliği adayları).
Entity proxy kararı verildi (K-05): `configs/entity.yaml` içinde `card1 + addr1`, addr1 NaN ayrı seviye; tüm adımlar anahtarı oradan okur.
`D1` anahtara girmez, Adım 3'te `card_age_days = floor(TransactionDT/86400) - D1` feature'ı olarak kullanılır.
Loader çıktısında `has_identity` kolonu ve `category` dtype'lar bulunur: Adım 3'te entity bazlı `groupby` işlemlerinde `observed=True` kullan
(aksi halde kategorik kolonlarda gözlenmeyen kombinasyonlar için boş gruplar üretilir, bellek ve süre artar).

## Bilinen sınırlar
- Spearman ve Cramér's V, tekrarlanabilir (seed 42) 100k satırlık rastgele örnek üzerindedir (hız içindir; split değildir); rank pairwise-complete
  yaklaşıktır. Kümeler V için tutarlıdır ama sınırdaki çiftler örnekle değişebilir.
- Entity tutar varyansı ve "tek işlemli" oranı, entity'nin gerçek kişi olup olmadığını kanıtlamaz; yalnızca davranış tarihçesi yeterliliğini ölçer.
- Rare eşiği (1e-4) ve küme eşiği (0,95) varsayılandır (`configs/profiling.yaml`); Adım 3'te gerekirse ayarlanır.
- D1n kontrolü etiketsizdir; D1n'in "kart ilk kullanım günü" olduğu doğrulanamaz, yalnızca davranışı (sabitlik, kapsama) ölçülür.
