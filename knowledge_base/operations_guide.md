---
doc_type: operations
---
# Operasyon Rehberi (Analist)

Bu rehber, bir işlem için platformun verdiği karara göre analistin ne yapacağını açıklayan örnek bir prosedürdür. Kurum politikası değildir; platformun karar türlerini ve bunların nasıl yorumlanacağını anlatır. Kararlar kural motorunun `final_decision` alanında gelir: block, review veya allow.

## Karar türleri ve kararın kaynağı

Kural motoru her işlem için tek bir karar üretir. `decision_source` alanı kararın kaynağını gösterir: kazanan kuralın kimliği (ör. R01), `score` (hiçbir kural karar vermedi ama boost öncesi skor inceleme eşiğine ulaştı) veya `default` (kural yok, skor eşiğin altında; varsayılan allow). Çakışan kurallarda önce öncelik (1 en yüksek), sonra önem, sonra block > review > allow sırası uygulanır. Bastırılan kurallar `suppressed_rules` alanında nedenleriyle listelenir.

İlgili kurallar: R01, R10

## Block kararı

Block, işlemin otomatik olarak durdurulması gereken kalıpla eşleştiği anlamına gelir (R01 kart testi, R02 yüksek tutar + yabancı ülke + gece). Analistin adımları:

1. `triggered_rules` ve `reasons` alanlarından tetiklenen kuralları ve gerçek değerleri oku.
2. Aynı entity'nin (kart grubu) son 24 saatteki işlemlerini incele; tekrar eden küçük tutarlar, farklı cihaz veya ülke kodları var mı bak.
3. Kart sahibine başka bir kanaldan ulaşarak işlemi doğrula; doğrulanana kadar blokajı koru.
4. Doğrulanırsa işlemi serbest bırak ve vakayı yanlış pozitif olarak not et; doğrulanamazsa kartı kısıtlama sürecine ilet.

Block kararı, öncelikten bağımsız olarak allow kuralını yener; yani güvenilir entity kuralı (R10) tetiklense bile block geçerlidir.

İlgili kurallar: R01, R02

## Review kararı (manuel inceleme)

Review, otomatik karar için yeterli kanıt yok ama risk sinyali var demektir. Adımlar:

1. Tetiklenen kuralları ve önem derecelerini sırala; high önemdeki kural (R03, R04, R05) medium veya low olandan (R06-R09, R11, R12) önce incelenir.
2. Tek bir zayıf kural (ör. yalnızca R04 veya R09) tetiklenmişse, kuralların bilinen sınırlarını hatırla: bu kurallar geniş kapsamlı ve ayrım gücü zayıftır, tek başlarına güçlü kanıt değildir.
3. Entity geçmişine bak: önceki işlem sayısı, kart yaşı, bilinen cihaz ve e-posta.
4. Karar ver: serbest bırak, ek doğrulama iste veya block'a yükselt. Gerekçeyi vakaya yaz.

İlgili kurallar: R03, R04, R05, R06, R07, R08, R09, R11, R12

## Skor kaynaklı review

`decision_source = score` ise hiçbir kural karar vermemiştir; boost öncesi skor (adjusted_score_unclipped) fit kümesinin q99 eşiğine (yaklaşık 1,07) ulaşmıştır. Bu durum anomali katmanlarının alışılmadık bir kombinasyon gördüğü ama tanımlı bir kalıba oturmadığı anlamına gelir. İnceleme sırasında hangi katmanın skora en çok katkı verdiğine (örneğin temporal, multivariate) ve context düzeltmelerine bak. Allow kuralı tetiklenmiş olsa bile skor bu eşiğe ulaştıysa allow geçersiz sayılır ve kurallar allow olmadan yeniden çözülür.

İlgili kurallar: R10

## Allow kararı

Allow, işlemin geçirilmesi demektir. İki yolu vardır: R10 (güvenilir entity) veya hiçbir kural tetiklenmemiş ve skor eşiğin altında (varsayılan). Analist normalde müdahale etmez. Ancak R10 allow kararının holdout'ta ortalamadan daha riskli çıktığı (precision 0,053, lift 1,53) bilinmelidir: entity bir kart grubudur ve güven kişiye değil gruba verilmiştir. Bu yüzden R10 allow'larından rastgele örnek alıp periyodik olarak kontrol etmek önerilir.

İlgili kurallar: R10

## Kural bazlı ilk kontroller: kart testi ve velocity

R01 için aynı kart grubunun son 1 saatteki işlem listesini çıkar; tutarlar küçük eşiğin (fit q10, 25,95 USD) altında ve ardışıksa kart testi büyük olasılıkla gerçektir. R03 için patlamanın tek entity'den gelip gelmediğine bak: cooldown öncesi holdout tetiklenmelerinin yaklaşık %99,6'sı tek bir kart grubundan gelmiştir; entity yüksek hacimli bir iş hesabı olabilir. Cooldown nedeniyle aynı patlama için yalnızca bir uyarı gelir, devamındaki işlemleri elle takip et.

İlgili kurallar: R01, R03

## Kural bazlı ilk kontroller: yüksek tutar, yabancı ülke, yeni kart

R02, R05 ve R11 için `addr2` değerine ve işlem saatine bak; addr2 = 87 ABD varsayımıdır, bu yüzden yabancı ülke bulgusu kesin değil yaklaşıktır. R04, R07 ve R12 için kartın ve entity'nin yaşını doğrula; D1 = kart yaşı da bir yorumdur. R08 için identity kaydının neden olmadığını kontrol et (ProductCD = W için identity zaten hiç olmaz, bu yüzden R08 W'yi dışlar). Tüm bu kurallarda yüksek tutar eşiği fit kümesinin TransactionAmt q95 değeridir (yaklaşık 441,95 USD).

İlgili kurallar: R02, R04, R05, R07, R08, R11, R12

## Kural bazlı ilk kontroller: tutar sapması ve e-posta

R06 için entity'nin geçmiş ortalamasını ve işlem sayısını kontrol et; ortalama en az 5 işleme dayanır. R09 için alıcı ve gönderen e-posta alanlarının neden farklı olduğunu araştır; hediye veya aracı alışveriş meşru olabilir, EDA'da etki ürün koduyla karışık görüldü ve kural bu yüzden en düşük önemdedir.

İlgili kurallar: R06, R09

## Yanlış pozitif geri bildirimi

Analistin kararı (serbest bırakma veya doğrulama) platformun eşiklerini otomatik değiştirmez. Kural veya eşik değişikliği configs/rules.yaml ve configs/rules_extra.json dosyalarında yapılır; değişiklik holdout etiketine bakılarak değil, ayrı bir doğrulama döneminde test edilerek yapılmalıdır (gelecek iş). Kural dosyaları değişince bilgi tabanı kartları `make rag-index` ile yeniden üretilir.
