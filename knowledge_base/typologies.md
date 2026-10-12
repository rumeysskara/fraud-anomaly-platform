---
doc_type: typology
---
# Fraud Tipolojileri

Bu belge platformun hedeflediği altı tipolojiyi kısaca anlatır ve her birini ilgili kural kimliklerine bağlar. Kalıplar uzman bilgisine dayanan hipotezlerdir; IEEE-CIS verisinde her birinin geçerliliği ayrıca kanıtlanmış değildir (bilinen sınırlar için kural kartlarına bakın).

## Card testing (kart testi)

Kart testi, çalıntı bir kartın çalışıp çalışmadığını anlamak için kısa sürede art arda küçük tutarlı işlemler denemektir. Tutarlar bilerek küçüktür, çünkü sahibinin dikkatini çekmez ve limit kontrolüne takılmaz. Platformda sinyal, aynı entity'nin son 1 saatte yaptığı önceki küçük tutarlı işlem sayısıdır (`small_amt_streak_1h`). Küçük tutar eşiği fit kümesinin TransactionAmt q10 değeridir.

- R01 bu kalıbı doğrudan yakalar ve block kararı verir.
- Context katmanındaki G1 koruması, kart testi sinyali varken hiçbir indirimin (iş saati, güvenilir entity, ürün) skoru ham skorun altına indirmesine izin vermez.
- R10 (trusted_entity_allow) kart testi sinyali varken geçersizdir.

İlgili kurallar: R01, G1, R10

## Velocity / burst (hız ve patlama)

Velocity, bir entity'nin kısa sürede alışılmadık sayıda işlem yapmasıdır. Tek başına yüksek sayı yeterli değildir, çünkü bazı entity'ler zaten sık işlem yapar. Bu yüzden sayı hem veri geneline göre uç (fit q99,9 = 12 önceki işlem/saat) hem de entity'nin kendi günlük ortalamasının 3 katından fazla olmalıdır (R03). Bir patlama tek uyarı üretsin diye R03 entity başına 1 saatte bir kez tetiklenir (cooldown).

Context tarafında C5, kendi normal ritmi yüksek olan yerleşik entity'lerde temporal katman ağırlığını yarıya indirir; gerçek bir değişim (günlük ortalamanın 3 katından fazlası) tam ağırlıkla kalır. C7 tatil tepesinde temporal kaynaklı skorları hafifçe düşürür.

İlgili kurallar: R03, C5, C7

## Hesap ele geçirme (account takeover)

Hesap ele geçirmede saldırgan, hesap sahibi uyurken veya dikkatsizken yüksek tutarlı alışveriş yapar. Platformdaki vekil sinyaller: düşük hacimli saat penceresi (tahmini yerel 00-06), yüksek tutar, alışılmadık ülke kodu, entity'nin kendi ortalamasından belirgin sapma ve daha önce görülmemiş cihaz/e-posta. Saat dilimi bir varsayımdır (veride yerel saat yoktur), bu yüzden sinyal yaklaşık kabul edilmelidir.

- C2 düşük hacim penceresinde yüksek tutarı çarpanla yükseltir (x1,15).
- R02 yüksek tutar, yabancı addr2 ve düşük hacim penceresini birlikte arar (block).
- R06 tutarın entity ortalamasının 5 katı olmasını arar; R10 yalnızca bilinen cihaz ve e-posta ile tutarın normal aralıkta olduğu güvenilir entity'yi allow'a çeker.

İlgili kurallar: R02, R06, C2, R10

## Yeni kart riski (bust-out / çalıntı kart)

Yeni açılmış veya ilk kez görülen bir kartla ilk günlerde büyük tutarlı alışveriş, hem çalıntı kart hem de bust-out dolandırıcılığında görülen bir kalıptır. Gerçek yeni müşteri genelde küçük tutarla başlar. Platformda kart yaşı D1 sütunundan alınır (D1 = kart yaşı bir yorumdur) ve D1 = 0 yeni kart sayılır.

- R04: yeni kart ve yüksek tutar (review). R12: aynı koşul tatil sezonunda.
- R07: entity'nin ilk işlemi ve yüksek tutar.
- C8: yeni kart ve yüksek tutar için çarpan x1,15.

Dikkat: R04 holdout'un yaklaşık %3'ünde tetiklenir ve ayrım gücü zayıftır (lift 1,33); tek başına karar gerekçesi olarak güçlü değildir.

İlgili kurallar: R04, R07, R12, C8

## Yabancı ülke ve adres uyuşmazlığı

Kartın ana pazarı dışında kullanılması klasik bir risk faktörüdür. Veride ülke kodu addr2'dir ve baskın değer 87 olup ABD kabul edilir (topluluk yorumu, doğrulanmış değil). addr2 baskın değerden farklıysa `foreign_addr2 = 1` olur. Ülke kodu hiç yoksa ve tutar 3 ondalıklıysa (olası kur çevrimi) kaynak doğrulanamaz. E-posta tarafında alıcı ve gönderen alanının farklı olması da bir uyuşmazlık sinyalidir ama meşru nedenlere de (hediye) sahiptir.

- R05: yüksek tutar ve yabancı addr2 (review); R02 aynı koşulun düşük hacim saatli, daha ciddi hali (block).
- R11: ülke kodu yok, 3 ondalıklı tutar, yüksek tutar.
- R09: alıcı ve gönderen e-posta farklı, yüksek tutar (en düşük önem).
- C6a: yabancı addr2 için x1,20; C6b: ülkesiz ve 3 ondalıklı tutar için x1,10.

İlgili kurallar: R02, R05, R09, R11, C6a, C6b

## Gece işlemleri

Düşük hacimli saat penceresinde (tahmini yerel 00-06) az sayıda müşteri aktiftir. Bu saatlerde yüksek tutarlı işlem hesap ele geçirme ve yabancı kart kullanımı kalıplarıyla birlikte görülebilir. Her gece işlemi şüpheli değildir; bu yüzden platform yalnızca yüksek tutar eşiğiyle birlikte gece sinyalini kullanır (C2, R02). Gündüz iş saatinde (09-18, hafta içi) geçmişi olan bir entity'nin işlemi için C1 küçük bir indirim (x0,90) uygular.

Yerel saat tahmini fit kümesinde hacmin en düşük olduğu 6 saatten türetilmiştir (-6 saat ofseti); gerçek saat dilimi bilinmez.

İlgili kurallar: R02, C2, C1
