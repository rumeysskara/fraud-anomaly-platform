# Veri Sözlüğü (IEEE-CIS Fraud Detection)

Kaynak: Veri sağlayıcı Vesta'nın Kaggle yarışma tartışmasındaki resmi açıklaması,
"Data Description (Details and Discussion)":
https://www.kaggle.com/c/ieee-fraud-detection/discussion/101203
Aşağıdaki tablo bu açıklamanın özetidir. Kolon adlarının çoğu gizlilik nedeniyle maskelenmiştir;
"resmi" olmayan yorumlar ayrıca belirtilmiştir.

## Transaction tablosu

| Kolon | Anlam (resmi) | Projede kullanım notu |
|---|---|---|
| TransactionDT | Bir referans zamandan itibaren geçen süre (saniye); gerçek zaman damgası değil | Referans tarih 2017-12-01 varsayımdır (configs/settings.yaml). Veri ~183 gün. |
| TransactionAmt | İşlem tutarı (USD) | Bazı tutarlar 3 ondalıklı ve addr1/addr2 boş; topluluk yorumu: yabancı para biriminden çevrilmiş olabilir (resmi değil). |
| ProductCD | Ürün/hizmet kodu (fiziksel ürün olmak zorunda değil) | W ürününde identity hiç yok (Adım 2 bulgusu). |
| card1-card6 | Kart bilgisi: tip, kategori, banka, ülke vb. | Kategorik. Entity anahtarı card1 + addr1 (K-05). |
| addr1 / addr2 | Alıcının (purchaser) fatura bölgesi / fatura ülkesi | addr2 baskın değer dışı = yabancı ülke proxy'si. |
| dist1 / dist2 | Mesafe: fatura adresi, posta adresi, posta kodu, IP adresi, telefon alanı vb. arasında | |
| P_emaildomain / R_emaildomain | Alıcı (purchaser) ve karşı taraf (recipient) email alan adı | R boşluğu yapısal: bazı işlemler karşı taraf gerektirmez; eksik veri hatası değil. |
| C1-C14 | Sayımlar (örn. karta bağlı kaç adres); gerçek anlam maskeli | Alıcı ve karşı taraf için; cihaz, IP, fatura adresi sayıları gibi. |
| D1-D15 | Zaman farkları (örn. önceki işlemden bu yana geçen gün) | D1 = kart yaşı olarak kullanılır (topluluk yorumu: ilk kullanımdan bu yana gün). |
| M1-M9 | Eşleşmeler (örn. kart üzerindeki isim ile adres) | Kategorik (T/F). |
| V1-V339 | Vesta'nın ürettiği özellikler: sıralama, sayım, entity ilişkileri (örn. kart+IP+email'in 24 saatte kaç kez görüldüğü) | Vesta: kategorik değil sayısal olarak ele alınmalı. |

Resmi kategorik kolonlar: ProductCD, card1-card6, addr1, addr2, P_emaildomain, R_emaildomain, M1-M9.

## Identity tablosu

Ağ bağlantısı (IP, ISP, proxy vb.) ve dijital imza (UA/tarayıcı/işletim sistemi/sürüm vb.) bilgileri;
Vesta'nın fraud koruma sistemi ve güvenlik ortaklarınca toplanır. Kolon adları maskelidir.
- id_01-id_11: sayısal; cihaz/IP/proxy puanları, giriş denemeleri, sayfada kalma süresi gibi davranışsal izler.
- Resmi kategorik: DeviceType, DeviceInfo, id_12-id_38.

## Etiket (isFraud) nasıl tanımlandı

Vesta'nın açıklaması özetle: Kartta raporlanan chargeback (itiraz) işlemi fraud (isFraud=1) sayılır. Ayrıca
**sonrasında gelen ve aynı kullanıcı hesabı, email adresi veya fatura adresine doğrudan bağlı işlemler de fraud
olarak etiketlenir.** 120 gün içinde bildirim yoksa işlem temiz (isFraud=0) kabul edilir. Bildirilmeyen
fraud'lar temiz görünebilir; Vesta bunu ihmal edilebilir sayıyor.

### Projeye etkisi
- Etiket entity düzeyinde yayılıyor. Aynı entity'nin sonraki işlemleri birlikte fraud olabilir;
  bu yüzden değerlendirmede satır bazlı metriklerin yanında entity bazlı bakış da anlamlıdır.
- Etiket gürültülüdür (bildirilmeyen fraud). Unsupervised yaklaşımın tercihini destekler; metrikler
  "gerçek fraud"un alt sınırı gibi yorumlanmalıdır.
- isFraud yalnızca değerlendirmede kullanılır (bkz. .claude/rules/data-leakage.md).
