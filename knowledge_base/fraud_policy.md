---
doc_type: policy
---
# Örnek Fraud Politikası

Bu belge platformun kurallarına dayanan ÖRNEK bir fraud politikasıdır; gerçek bir kurumun politikası değildir. Amacı, kural motoru ve context katmanının hangi ilkelere göre karar verdiğini politika dilinde özetlemektir. Eşik ve kural ayrıntıları kural kartlarında, analist adımları operasyon rehberindedir.

## Amaç ve kapsam

Politika, kartla yapılan çevrimiçi işlemlerde dolandırıcılık riskini azaltırken meşru müşterilerin gereksiz yere durdurulmasını (yanlış pozitif) sınırlamayı amaçlar. Kapsam her işlem için tek bir karardır: block (durdur), review (manuel inceleme) veya allow (geçir). Kararı her zaman kural motoru verir; anomali skoru ve context düzeltmesi bu karara girdi sağlar. Müşteri kimliği bilinmediği için "müşteri" yerine `card1 + addr1` ile tanımlanan kart grubu (entity) kullanılır; bu grup bir kişi değildir ve güven kişiye değil gruba verilir.

İlgili kurallar: R01, R10

## Otomatik durdurma (block) ilkeleri

Yalnızca güçlü ve tanımlı bir dolandırıcılık kalıbı otomatik durdurma gerekçesidir. Örnek politikada iki kalıp bu düzeydedir:

1. Kart testi: aynı kart grubunun son 1 saatte art arda küçük tutarlı işlemler yapması (küçük tutar = fit kümesinin TransactionAmt q10 değeri, 25,95 USD).
2. Yabancı ülke + düşük hacimli gece saati + yüksek tutar birlikte (yüksek tutar = fit q95, 441,95 USD).

Block kararı başka hiçbir kural tarafından geri alınamaz; güvenilir entity (allow) kuralı tetiklense bile block geçerlidir. Durdurulan işlem, kart sahibi başka bir kanaldan doğrulanana kadar bekletilir.

İlgili kurallar: R01, R02, R10

## Manuel inceleme (review) ilkeleri

Risk sinyali olan ama tek başına durdurmayı haklı çıkarmayan durumlar manuel incelemeye gider: entity'nin kendi ritmini aşan işlem patlaması, yeni kartta veya ilk işlemde yüksek tutar, yabancı ülkeden yüksek tutar, entity'nin kendi ortalamasından belirgin sapma, identity kaydı olmayan yüksek tutar, kur çevrimi görünümlü tutar ve alıcı/gönderen e-posta uyuşmazlığı. Birden fazla review kuralı tetiklenirse en yüksek öncelikli olan karar kaynağıdır, diğerleri gerekçeleriyle birlikte kayda geçer.

Hiçbir kural karar vermese bile anomali skoru (kural artışı öncesi, context düzeltmeli) fit kümesinin en yüksek %1'lik dilimine (q99 eşiği, yaklaşık 1,07) ulaşırsa işlem incelemeye alınır. Bu, tanımlı kalıplara uymayan olağandışı işlemlerin gözden kaçmamasını sağlar.

İlgili kurallar: R03, R04, R05, R06, R07, R08, R09, R11, R12

## Geçirme (allow) ve güvenilir müşteri ilkeleri

Kural tetiklenmeyen ve skoru inceleme eşiğinin altında kalan işlemler geçirilir. Uzun geçmişi olan, kendi normal tutar aralığında işlem yapan, daha önce kullandığı cihaz ve e-posta ile gelen ve adresi (addr1) bilinen kart grubu "güvenilir" sayılır ve geçirilir. Adresi boş kart grupları güvenilir sayılmaz, çünkü anahtar orada yalnızca kart numarası grubudur ve birçok kartı birleştirir. Güvenilir statüsü üç sınırla korunur:

- Kart testi sinyali varken güvenilir statüsü geçersizdir; hiçbir indirim skoru ham skorun altına indiremez.
- Herhangi bir block kuralı güvenilir statüsünü yener.
- Skor inceleme eşiğine ulaşmışsa allow geçersiz sayılır ve işlem incelemeye gider.

Güvenilir statüsü kişiye değil kart grubuna verildiği için allow kararlarından periyodik olarak örnek alınıp kontrol edilmesi önerilir.

İlgili kurallar: R10, C4, G1

## Bağlam (context) düzeltmeleri

Aynı anomali skoru her bağlamda aynı riski taşımaz. Politika, skoru iş bağlamına göre sınırlı ölçüde düzeltmeye izin verir: geçmişi olan bir kart grubunun yerel iş saatlerinde veya hafta sonundaki işlemleri hafifçe indirilir; gece yüksek tutar, yeni kartta yüksek tutar ve sınır ötesi işlem hafifçe artırılır. Toplam düzeltme 0,5 ile 1,5 kat arasında sınırlıdır, böylece hiçbir bağlam tek başına kararı belirleyemez.

İlgili kurallar: C1, C2, C3, C4, C6a, C8, G1

## Açıklanabilirlik ve LLM'in rolü

Her karar, tetiklenen kuralları, işlemin gerçek değerlerini ve bastırılan kuralları gerekçeleriyle birlikte içermelidir. Analist "neden" sorusunun cevabını kural motorunun çıktısında bulabilmelidir. Yerel LLM ile üretilen açıklama yalnızca "destek bilgisi"dir: kararı, skoru veya eşikleri değiştiremez, bilgi tabanında cevap yoksa bunu açıkça söyler.

İlgili kurallar: R01, R10

## Veri ve değişiklik yönetimi

- Gerçek dolandırıcılık etiketi kural, eşik ve ağırlık seçiminde kullanılmaz; yalnızca sonradan değerlendirme (precision, recall, yanlış pozitif oranı) için okunur.
- Eşikler zamana göre ilk %80'lik fit kümesinden öğrenilir; son %20 yalnızca ölçüm içindir.
- Kural veya eşik değişikliği kod değil config değişikliğidir (configs/rules.yaml, configs/rules_extra.json, configs/context.yaml). Değişiklik holdout sonucuna bakılarak değil, ayrı bir doğrulama döneminde test edilerek yapılmalıdır.
- Analistin yanlış pozitif geri bildirimi eşikleri otomatik değiştirmez; kayda geçer ve bir sonraki kural gözden geçirmesinde girdi olur.

İlgili kurallar: R10
