# Adım 3 öncesi kısa EDA

Betik: `scripts/eda_report.py` (`SAMPLE_N` desteklenir). Fonksiyonlar: `src/profiling/eda.py`, `src/profiling/eda_figures.py` (etiketsiz),
`src/evaluation/fraud_rate.py` (etiketli). Her tablo `reports/eda/` altında csv + aynı verinin png grafiği olarak durur (`a_*` = bölüm A, `b_*` = bölüm B).
Tarih: referans tarih (2017-12-01, `settings.yaml`) + TransactionDT; bu bir **varsayımdır**, gerçek takvim tarihi bilinmiyor.
Grafiklerde başlık, eksen etiketi ve değer etiketleri var; renk körlüğüne uygun palet kullanıldı. (Not: projede `dataviz` adlı bir skill dosyası bulunamadı,
grafikler genel okunabilirlik ilkeleriyle üretildi.)

**isFraud kullanıldı mı:** A bölümünde hayır. B bölümünde evet, yalnızca fit kümesinde ve yalnızca tanımlayıcı olarak. Etiket yalnızca
`src/evaluation/fraud_rate.py` içinden okundu; `src/profiling` ve script etiketi doğrudan okumaz (script `y`'nin fit kısmını evaluation fonksiyonuna verir).

## A. Etiketsiz bulgular (tüm veri, 590.540 satır)

### Kategorik dağılımlar (`a_productcd`, `a_card4`, `a_card6`, `a_p_emaildomain`, `a_devicetype`)
| Değişken | Dağılım (sayı ve pay `a_*.csv` içinde) |
|---|---|
| ProductCD | W %74,5, C %11,6, R %6,4, H %5,6, S %2,0 |
| card4 | visa %65,2, mastercard %32,0, american express %1,4, discover %1,1, eksik %0,3 |
| card6 | debit %74,5, credit %25,2, eksik %0,3; "debit or credit" (30) ve "charge card" (15) ihmal edilebilir |
| P_emaildomain (ilk 10) | gmail.com %38,7, yahoo.com %17,1, eksik %16,0, hotmail.com %7,7, anonymous.com %6,3, aol.com %4,8, comcast.net %1,3, icloud.com %1,1, outlook.com %0,9, msn.com %0,7 |
| DeviceType | eksik %76,2, desktop %14,4, mobile %9,4 |

Yorum: veri tek ürüne (W) ve iki kart ağına (visa, mastercard) yoğunlaşmış. DeviceType'ın %76'sı eksik; bu, identity kaydı olmayan işlemlerle aynı yapıdır (Adım 1: identity yalnızca %24,4).

### Haftalık döngü (`a_acf`, `a_weekday_profile`)
Günlük işlem sayısı serisinin (182 gün) otokorelasyonu: ham seride lag 7 = 0,50 ve lag 6 (0,45) ile lag 8'den (0,34) yüksek, yani lag 7'de yerel bir tepe var; ama seri
aynı zamanda azalan bir eğilim taşıdığı için ham değerler lag arttıkça düşüyor. Eğilimi çıkarmak için serinin ortalanmış 7 günlük hareketli ortalaması
çıkarılınca lag 7 = 0,38 ve lag 14 = 0,41, diğer lag'ler çoğunlukla sıfıra yakın veya negatif. Bu, zayıf-orta düzeyde bir haftalık döngüye işaret eder.
Gün profilinde (referans tarihe göre gün adları) Pazartesi günlük ortalamanın %83'ü, Cumartesi %117'si.

### Günlük hacim: 20-27. gün tepesi ve 92. gün sıçraması (`a_daily_volume`, `a_peak_windows`, `a_spike`)
- **İstenen pencere (gün 20-27 = 2017-12-21 ... 2017-12-28):** günlük ortalama 5.375, çevresindeki 7+7 günün ortalamasının 1,32 katı.
- **Veride en yüksek 8 günlük pencere gün 18-25 (2017-12-19 ... 2017-12-26):** günlük ortalama 5.884, çevresinin 1,53 katı. Tepe gün 22 (2017-12-23, 6.852 işlem);
  26. günde (2017-12-27) ani düşüş (5.742 -> 3.458). Yani tepe, gün ofseti tanımına göre 2 gün erken başlıyor ve 25-26. günde bitiyor; 20-27 penceresi tepenin sonunu ve sonrasındaki düşüşü de kapsıyor.
  Zamanlama Noel dönemiyle örtüşüyor; bu bir örtüşme, neden değil (tarih referans varsayımına bağlı).
- **92. gün (2018-03-03):** 6.252 işlem; önceki güne göre 1,56 kat (4.007), önceki 7 günün ortalamasına göre 1,95 kat (3.199). Sonraki gün 4.524'e iniyor, sonraki 7 günün
  ortalaması önceki 7 günün 1,09 katı: kalıcı bir seviye kayması değil, birkaç günlük bir sıçrama (yine de gün 91'de 4.007 ile yükseliş başlamış).

### En sık 20 TransactionAmt (`a_top_amounts`)
En sık değerler 59,00 (%5,2), 117,00 (%4,9), 107,95 (%4,1), 57,95 (%4,0), 100,00 (%3,4), 50,00 (%2,9), 49,00 (%2,7). İlk 4 değer işlemlerin %18,1'i, ilk 20 değer %46,2'si.
Tutarların yarıya yakını az sayıda "yuvarlak veya fiyat-noktası" değerinde toplanıyor (.95 ve tam sayı fiyatlar). Bu, tutar tabanlı anomali sinyalinde "alışılmış tutar" kavramının anlamlı olabileceğini düşündürür.

## B. Etiketli bulgular (yalnızca fit kümesi)

Bu bulgular yalnızca fit döneminden çıkarılmıştır; holdout'a bakılmamıştır. Kural ve ağırlık seçimi bu tablolara göre ayarlanmamıştır, yalnızca iş kurallarının makullüğünü kontrol etmek için kullanılır.

Fit kümesi: ilk %80 (472.432 satır, 16.599 pozitif); **fit taban oranı %3,51** (`b_base_rate.csv`). Tablolar n, pozitif sayısı, oran ve %95 Wilson aralığı verir;
n < 100 olan gruplar `small_n` ile işaretli (grafikte gri-taramalı). Yorumlar betimleyicidir, nedensellik iddiası taşımaz; gruplar birbiriyle iç içe geçmiş olabilir (örn. ProductCD, has_identity ve DeviceType ilişkili).

| Grup | Fraud oranı (n) | Not |
|---|---|---|
| ProductCD: C / S / H / R / W | %11,3 (56.410) / %6,2 / %4,6 / %3,6 / %2,1 (346.001) | C taban oranının yaklaşık 3 katı, W altında |
| card4: discover / visa / mastercard / amex | %7,4 (5.394) / %3,5 / %3,5 / %2,9 | discover diğerlerinden yüksek |
| card6: credit / debit | %6,7 (121.716) / %2,4 (349.843) | "charge card" (15) ve "debit or credit" (30) küçük n; oran 0, anlamsız |
| DeviceType: mobile / desktop / eksik | %9,9 (46.093) / %6,2 (71.545) / %2,1 (354.794) | |
| has_identity: True / False | %7,6 (120.464) / %2,1 (351.968) | identity kaydı olanlarda oran yaklaşık 3,5 kat |
| P_emaildomain (ilk 10): outlook / hotmail / gmail / ... / att.net | %9,2 (4.080) / %5,2 / %4,4 / ... / %0,6 (3.133) | yahoo %2,3, aol %2,2, anonymous %2,3; eksik %3,0; tam tablo `b_p_emaildomain.csv` |
| D1 = 0 (yeni kart) / D1 > 0 / eksik | %4,1 (231.279) / %2,9 (240.217) / %2,9 (936) | fark var; ProductCD karışımı için düzeltme yapılmadı |
| addr2: baskın değer (87) / diğer / eksik | %2,4 (414.740) / %10,4 (3.931) / %11,4 (53.761) | eksik ve baskın olmayan addr2'de oran yüksek |
| P != R / P = R (ikisi dolu) | %2,8 (20.121) / %9,3 (85.848) | **P ve R eşitken oran daha yüksek**; yalnızca P dolu (R eksik) %2,0 (292.877), P eksik %3,0 (73.586) |

Saat bazında (`b_hour`, referans tarihli saat): fraud oranı 7-9. saatlerde %10-10,6'ya çıkıyor (7: %10,1, 8: %9,7, 9: %10,6); 13-15. saatlerde en düşük (%2,1-2,5);
akşam saatlerinde taban oranına yakın (%3,2-3,9). Dikkat: 7-9. saatlerde işlem hacmi çok düşük (saat başına 1.844-3.156 işlem; akşam ~33.000), yani oran yüksek ama
mutlak fraud sayısı küçük (195-319) ve aralıklar geniş. Saat dilimi bilinmediği için mutlak saat yorumlanmaz.

TransactionAmt desilleri (`b_amount_decile`, sınırlar fit'ten): oran monoton değil; en düşük (D1: 0-26) %5,4 ve en yüksek (D10: 277+) %5,2 uçlarda yüksek, ortada (D4 49-58: %2,0, D7 100-117: %1,9) düşük.
Yani tutar ile fraud oranı arasında doğrusal bir ilişki yok; uçlarda artış var.

### Kural makullüğü için okuma (tuning değil)
Bu tablolar, yeni kart, identity yokluğu, addr2, e-posta eşleşmesi, saat ve tutar uçları gibi kuralların hangi yönde "makul" görüneceğini gösterir. Bunlardan bazıları
sezgiyle ters olabilir (örn. P = R'de oran yüksek, P != R'de düşük); bu tür kuralların eşiği veya ağırlığı bu tablolardan çıkarılmamalıdır.

## Sınırlar
- Referans tarih varsayım; gün adları, saatler ve "Noel dönemi" yorumu bu varsayıma bağlı.
- B bölümü tek değişkenli, ilişkili gruplar nedeniyle birbirinden bağımsız değildir; çok sayıda karşılaştırma yapıldığı için küçük farklar şansa bağlı olabilir.
- Oranlar fit dönemine özgüdür; holdout'ta aynı değerler beklenmez ve kontrol edilmedi.
- EDA sabitleri (lag aralığı, pencere uzunluğu, 92. gün, ilk-N, `small_n` eşiği 100) `src/profiling/eda.py` içinde adlandırılmış sabitlerdir; `configs/` yazma izni bu iş için olmadığından YAML'a taşınmadı.
- Günlük seri 182 günlük; haftalık döngü için yalnızca ~26 hafta var.
