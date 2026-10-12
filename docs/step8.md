# Adım 8 - Yerel RAG (bilgi tabanı, retrieval, LLM bağlamı)

**isFraud kullanıldı mı: hayır.** RAG katmanı (`src/rag/`, `knowledge_base/`, `configs/rag.yaml`, `scripts/build_rag_index.py`) etiketi hiçbir yerde okumaz; testle de doğrulanır (`tests/rag/test_no_label.py`). Bilgi tabanındaki holdout sayıları (precision, lift) Adım 6-7 raporlarından (`docs/step6.md`, `docs/step7.md`) metin olarak alınmıştır; hiçbir kural, eşik veya retrieval ayarı bu sayılara göre seçilmedi.

Karar kayıtları: K-28 ... K-33 (`docs/decisions.md`).

## Ne yapıldı
Analistin "bu işlem neden review aldı?", "R03 nedir?", "block kararında ne yapmalıyım?" gibi sorularını, projenin kendi kural ve politika belgelerinden, yalnızca yerel modellerle (Ollama) cevaplayan bir RAG hattı kuruldu.

```
configs/rules.yaml, rules_extra.json, context.yaml ──(kb_builder)──> knowledge_base/generated/*.md  (otomatik)
knowledge_base/{typologies,feature_dictionary,operations_guide}.md (elle) ─┐
                                                                           ├─(chunker)─> chunk'lar
                                                                           │            ─(bge-m3)─> FAISS IndexFlatIP
                                                                           │                       artifacts/rag/{index.faiss,chunks.jsonl}
soru (+ kural motoru explain çıktısı) ─> HybridRetriever ─> PromptBuilder ─> qwen2.5:7b ─> RAGAnswer
```

Çalışma zamanında (API, Adım 10) indeks kurulmaz; `Container.rag_service` yalnızca `artifacts/rag/` içindeki hazır indeksi yükler.

## Modeller ve gerekçe (K-28)
| Bileşen | Seçim | Gerekçe |
|---|---|---|
| Embedding | `bge-m3` (Ollama) | Yerel ve ücretsiz; çok dilli retrieval için eğitilmiş, Türkçeyi destekliyor; ~1,2 GB |
| LLM | `qwen2.5:7b` (Ollama), temperature 0 (K-33) | Yerel; Türkçe konuşabiliyor; 4-bit ~4,7 GB ile 16 GB RAM'e sığıyor. Yedek ad `qwen2.5:3b` yalnızca config'te durur, birincil model kurulu değilse denenir (bu makinede kurulu değil, denenmedi) |
| Vector store | FAISS `IndexFlatIP`, L2-normalize vektörler (= kosinüs) | Yerel; KB 52 chunk olduğu için kesin (flat) arama yeterli; seed 42 |

Model karşılaştırması yapılmadı (kullanıcı kararı). Başka bir embedding veya LLM denenmedi; "bge-m3 en iyisi" iddiası yoktur, yalnızca gerekçeli bir seçimdir.

## Bilgi tabanı (K-29)
52 chunk, 5 belge türü:

| Belge | Üretim | Chunk | Bölümler |
|---|---|---|---|
| `knowledge_base/generated/rule_cards.md` | OTOMATİK (`rules.yaml` + `rules_extra.json` + `rule_notes.yaml`) | 14 | kural özeti tablosu, çakışma çözümü, R01-R12 (her kural 1 chunk) |
| `knowledge_base/generated/context_cards.md` | OTOMATİK (`context.yaml` + `rule_notes.yaml`) | 14 | özet tablosu, çarpan birleşimi, C1-C9b, G1 |
| `knowledge_base/typologies.md` | elle | 7 | card testing, velocity/burst, hesap ele geçirme, yeni kart riski, yabancı ülke/adres uyuşmazlığı, gece işlemleri (+ giriş); her biri "İlgili kurallar:" satırıyla kural ID'lerine bağlı |
| `knowledge_base/feature_dictionary.md` | elle | 7 | tutar, entity geçmişi/velocity, kart/cihaz, coğrafya/e-posta, zaman, skor alanları |
| `knowledge_base/operations_guide.md` | elle | 10 | karar türleri, block, review, skor kaynaklı review, allow, kural bazlı ilk kontroller (3 bölüm), yanlış pozitif geri bildirimi |

**Kural kartı içeriği:** kural ID, ad, karar, öncelik, önem, risk artışı, bayrak, etiketler, cooldown (varsa) tablosu; koşulun düz Türkçe madde madde yazımı (öğrenilmiş eşiklerin gerçek değeriyle, örn. "441,95 (fit TransactionAmt q95)"); config açıklaması; gerekçe; bilinen sınırlar. Üretilen dosyalar `<!-- AUTO-GENERATED -->` yorumu ve görünür "otomatik üretildi, elle düzenlemeyin" notu taşır. Kural değişince `make rag-index` kartı yeniden üretir; testte (`test_card_follows_a_changed_rule`) bir kuralın boost'u ve koşulu değiştirilip R12 silinir, kartın buna uyduğu doğrulanır.

**Gerekçe ve bilinen sınırlar nereden:** `knowledge_base/sources/rule_notes.yaml`. Bu, `docs/step7.md` (Kurallar tablosu, tetiklenme yoğunlaşması, EDA tutarlılık kontrolü, Bilinen sınırlar), `docs/step6.md` ve `docs/assumptions.md` içinden elle derlenmiş kısa Türkçe notlardır (holdout ve fit tetiklenme sayıları, lift, entity proxy sınırı, varsayımlar). Seçenekler (otomatik ayrıştırma vs küçük bir yaml) K-29'dadır. Sınır: bu notlardaki sayılar elle girilir; `step7.md` yeniden hesaplanırsa dosya elle güncellenmelidir.

Her chunk'ın metadata'sı: `chunk_id`, `doc_type`, `rule_ids`, `source_path`, `heading_path` (+ `part`, `n_parts`). `rule_ids`, bölüm başlığındaki kural ID'sinden (`## R01 - card_testing`) ve bölümdeki "İlgili kurallar:" satırından çıkarılır. Örnek chunk id'leri: `rule_cards#r01-card-testing`, `context_cards#g1-card-testing-floor`, `typologies#card-testing-kart-testi`.

## Chunking (K-30)
`markdown-it-py` ile ayrıştırılır. Bir başlık bölümünün gövdesi bir chunk'tır ve metin başlık yolunu (`Kural Kartları (kural motoru, Adım 7) > R01 - card_testing`) taşır. Tablolar asla bölünmez (testle doğrulanır: sınırın çok üstündeki tablo tek chunk'ta kalır). Karakter sayısıyla kesim yoktur. Yalnızca güvenlik amaçlı üst sınır vardır: tahmini 768 token (3 karakter = 1 token kaba tahmin); aşılırsa bölüm paragraf/blok sınırlarından, çok uzun listeler madde sınırlarından bölünür (id'ye `.p1`, `.p2` eklenir). Mevcut KB'de hiçbir chunk bölünmedi (en uzun chunk 1.781 karakter). İlk deneme 512 tokendi; R10 kartını gereksiz bölünce 768'e çıkarıldı (bge-m3 ve LLM bağlamı bunu rahat taşır).

Neden yapıya duyarlı: kural kartı veya prosedür adımları ortasından kesilirse anlam bozulur; başlık yolu embedding'e konu bilgisini ekler; kural başına chunk, "tetiklenen kuralın kartını getir" filtresini mümkün kılar.

## Retrieval (K-31)
`Retriever.retrieve(query, k, filters=None)` (arayüze geriye uyumlu ekleme). Hibrit çalışır:
1. `filters["rule_ids"]` (açıklanan işlemde tetiklenen kurallar) varsa, her kural için semantik skoru en yüksek KART chunk'ı (rule_card/context_card) en fazla `metadata_quota` (2) kadar öne alınır.
2. Kalan yerler saf semantik aramayla (kosinüs) doldurulur, tekrarlar ayıklanır, toplam `k` (varsayılan 4).
3. Her sonuç `metadata["retrieval"]` ile "metadata" veya "semantic" işaretlenir. `filters["doc_types"]` tüm sonuçları belge türüyle sınırlar.

## LLM bağlamı ve çıktı (K-32)
Prompt şablonu `configs/rag.yaml` içindedir. Sistem talimatı: yalnızca BAĞLAM'dan Türkçe cevap ver; bağlamda yoksa aynen "Bilgi tabanında bu konuda bilgi yok" de; tahmin etme, kural/eşik/sayı uydurma; kaynak chunk id'lerini köşeli parantezle yaz. Sistem mesajı = talimat + numaralı parçalar (`[chunk_id] başlık` + metin). Kullanıcı mesajı = (varsa) kural motoru çıktısının seçili alanları (`final_decision`, `triggered_rules`, `flags`, `reasons`, skorlar) + soru + "Kaynaklar:" hatırlatması. `LLMClient.generate(prompt, context)`: `prompt` kullanıcı, `context` sistem mesajıdır.

`RAGService.answer(question, explanation=None, rule_ids=None, k=None) -> RAGAnswer`:
```
answer        : str | null            # null => LLM yok
sources       : [{chunk_id, heading, doc_type, rule_ids, score, retrieval}]
cited_ids     : [chunk_id]            # cevap metninde geçen kaynak id'leri
used_context  : [chunk metni]
flags         : ["llm_unavailable"]   # LLM yoksa
```
Dayanıklılık: Ollama kapalıysa veya LLM kurulu değilse retrieval sonucu `answer=null` ve `llm_unavailable` ile döner (çökme yok). Embedding modeli yoksa `EmbeddingUnavailableError`, indeks yoksa `IndexNotBuiltError` (mesaj `make rag-index` der); Ollama tamamen kapalıyken retrieval de yapılamaz, yani `RAGService` cevap üretemez. `/rag/query` bu durumda `llm_status="unavailable"` (embedding) veya 503 (indeks yok) döner; ExplainerAgent (Adım 9) ise iki hatada da şablon açıklamaya düşer. Timeout'lar `configs/rag.yaml` içindedir. Retry yoktur.

## Güvenilirlik katmanları (K-33, ek tur)
İlk sürümde 7B model bağlam dışı ifade uydurmuş ve KB'de olmayan bir soruya yanlış bir sayı vermişti (aşağıdaki "ilk sürüm" notları). Bunun üzerine kullanıcı kararıyla üç önlem eklendi:
1. **Few-shot ve temperature 0:** sistem mesajına bir "bilgi yok" ve bir "bilgi var" örneği eklendi; talimat "bilgi tabanında bu konuda bilgi yok" cümlesini istiyor.
2. **Abstain eşiği:** sorunun en iyi SEMANTİK kosinüs skoru `retrieval.abstain_threshold` (0,45) altındaysa LLM çağrılmaz. Skor, filtresiz aramanın en iyisidir; tetiklenen kural kartları metadata ile öne alınsa bile bu skoru etkilemez (hibrit etkileşimi: kartlar abstain'i gizleyemez, testle doğrulanır). Açıklanan işlem (`explanation`) verilse de aynı soru-skor kuralı geçerlidir.
3. **Kaynak kontrolü:** cevapta geçen `[...#...]` id'lerinin hepsi getirilen chunk'lardan olmalı ve en az biri bulunmalı; yoksa `grounded=false` ve cevaba uyarı eklenir. LLM'in kendisi "bilgi yok" derse `abstained=true` olur ve eklediği kaynaklar atılır.

`RAGAnswer` yeni alanlar: `abstained`, `grounded`, `top_score`, `warning`. Bu bayraklarla Adım 9'da RAG cevabı "destek bilgisi" olarak etiketlenir; karar kural motorunda kalır.

### Eşik seçimi: skor dağılımı (etiketle ilgisi yok)
13 soru (10 KB-içi + 3 KB-dışı, `tests/rag/retrieval_questions.yaml`), her biri için filtresiz en iyi kosinüs:

| Skor | Tür | Soru |
|---|---|---|
| 0,341 | KB-dışı | Türkiye'nin başkenti neresidir? |
| 0,533 | KB-içi | small_amt_streak_1h feature'ı neyi ölçer? |
| 0,561 | KB-dışı | Kuralların holdout'taki toplam fraud yakalama oranı nedir? |
| 0,596 | KB-dışı | Kredi kartı faiz oranları bankalarda nasıl hesaplanır? |
| 0,623-0,687 | KB-içi (9 soru) | diğer dokuz soru |

Dağılımlar örtüşüyor: en düşük KB-içi skor (0,533, kısa ve İngilizce tanımlayıcılı soru) iki KB-dışı sorunun altında. Tek eşik ikisini ayıramaz. Seçenekler: 0,45 (yanlış abstain 0/10, doğru abstain 1/3) veya 0,60 (doğru abstain 3/3, yanlış abstain 1/10, ama 13 soruya uydurulmuş ve 0,596'ya razor-thin). **0,45 seçildi**: geçerli bir analist sorusunu reddetmemek, yakın konulu KB-dışı soruları kaçırmaktan daha kötü kabul edildi; kaçanlar ikinci hatta (few-shot, LLM'in kendi cevabı, kaynak kontrolü) yakalanıyor. Örnek sayısı çok küçüktür; eşik bağımsız bir sette doğrulanmadı.

| Ölçüt (eşik 0,45) | Değer |
|---|---|
| Doğru abstain (eşik, LLM'siz) | 1/3 = 0,33 |
| Yanlış abstain (KB-içi soruyu reddetme) | 0/10 = 0,00 |
| Uçtan uca doğru abstain (eşik + LLM'in kendi "bilgi yok" cevabı, gerçek model) | 3/3 |

Uçtan uca: Türkiye sorusu eşikte (LLM çağrılmadı, 0,2 sn); faiz oranı ve holdout yakalama oranı soruları eşiği geçti, `qwen2.5:7b` "Bilgi tabanında bu konuda bilgi yok" dedi (`abstained=true`). Her ikisinde model ayrıca ilgisiz kaynak id'leri eklemişti; servis bunları siler.

## Gerçek çalıştırma: örnek sorgular
**İlk sürüm** çıktıları (temperature 0,1, güvenilirlik katmanları öncesi); ardından aynı soruların ek tur sonrası sonuçları verilmiştir. Aşağıdakiler bu makinede gerçek indeks, `bge-m3` ve `qwen2.5:7b` ile alınmış çıktılardır (temperature 0,1; her cevap 16-34 sn sürdü). Cevap metinleri aynen alınmıştır (yalnızca satır başları boşluğa çevrildi).

**1) Hibrit: işlem açıklaması + soru** (tetiklenen kurallar R04 ve R06; kural motoru çıktısı elle oluşturulmuş örnek bir `explain_dict`)
- Soru: "Neden bu işlem review aldı ve analist ne yapmalı?"
- Getirilen: `rule_cards#r04-new-card-high-amount` (metadata, 0,475), `rule_cards#r06-amount-deviation` (metadata, 0,463), `operations_guide#review-karari-manuel-inceleme` (semantic, 0,612), `operations_guide#operasyon-rehberi-analist` (semantic, 0,593)
- Cevap: "Bu işlem, yeni kart kullanımları ile yüksek tutar işlemler arasında bir kombinasyon nedeniyle review kararı aldı. Kurallar: R04 - new_card_high_amount: Yeni kart (D1=0) ile yüksek tutar (520.00 USD, eşik 441.95). R06 - amount_deviation: Tutar entity'nin geçmiş ortalamasının 8.7 katı ve en az 12 işlem yapılmış. **Aristoteles'in yasası gereği**, bu iki kuralların tetiklenmesi sonucu risk sinyali oluştu ve otomatik karar için yeterli kanıt bulunmadığı için manual review kararı verildi. Analist, kurallara bakarak ve entity'nin geçmiş işlem bilgilerini incelemeli ve serbest bırakma, ek doğrulama talebi veya block'a yükseltme gibi kararlar almalıdır. Kaynaklar: [rule_cards#r04-new-card-high-amount] [rule_cards#r06-amount-deviation]"
- Değerlendirme: Doğru kartlar getirildi ve kaynaklar doğru yazıldı. Ancak model bağlamda olmayan bir ifade uydurdu ("Aristoteles'in yasası") ve R06'nın "en az 5 geçmiş işlem" şartını işlemin 12 geçmiş işlemi olarak yanlış aktardı. Küçük modelin bir sınırıdır; sistem talimatına rağmen oluştu.

**2) Semantik: gece işlemleri**
- Soru: "Gece saatlerinde yüksek tutarlı işlem neden riskli sayılır?"
- Getirilen: `typologies#gece-islemleri` (0,632), `typologies#hesap-ele-gecirme-account-takeover` (0,593), `rule_cards#r02-high-amount-foreign-low-volume` (0,552), `context_cards#c2-low-volume-high-amount` (0,535)
- Cevap: "Gece saatlerinde (tahmini yerel 00-06) yüksek tutarlı işlem riskli sayılır çünkü bu saatlerde düşük müşteri hacmi olduğu için normal davranıştan sapma daha kolay algılanır ve şüpheli görünür. Düşük hacimli saatlerde yapılan yüksek tutarlı işlemler hesap ele geçirme kalıbını destekleyebilir. Kaynaklar: [typologies#gece-islemleri] [rule_cards#r02-high-amount-foreign-low-volume]" - kaynaklı ve bağlamla uyumlu.

**3) Semantik: operasyon**
- Soru: "Block kararı verilen bir işlemde analist ne yapmalı?"
- Getirilen: `operations_guide#block-karari` (0,751), `operations_guide#operasyon-rehberi-analist` (0,646), `operations_guide#allow-karari`, `operations_guide#yanlis-pozitif-geri-bildirimi`
- Cevap: rehberin dört adımını (tetiklenen kuralları oku, entity'nin son 24 saatini incele, kart sahibini başka kanaldan doğrula, doğrulanırsa serbest bırak/doğrulanamazsa kısıtlama sürecine ilet) sırasıyla aktardı; kaynak: [operations_guide#block-karari].

**4) Bilgi tabanının cevaplayamadığı soru (başarısız örnek)**
- Soru: "Kuralların holdout'taki fraud yakalama oranı nedir?"
- Getirilen: tipoloji ve R04/R05/R06 kartları (en yüksek skor 0,599).
- Cevap: "Kurallar holdout'da %3,1'inde tetiklenir. [Kaynaklar: rule_cards#r04-new-card-high-amount]". Bu cevap soruyu yanıtlamıyor: %3,1, R04'ün tetiklenme payıdır, yakalama oranı değildir. Beklenen davranış "Bilgi tabanında bu bilgi yok." idi (KB'de kural bazlı precision var, toplam yakalama oranı yok). 7B model grounding talimatını burada izlemedi.

Örnek 1 ve 4, modelin doğruluğunun garanti olmadığını gösterir; çıktı analiste destek bilgisidir, karar kural motorundadır.

**Ek tur sonrası yeniden deneme (temperature 0, few-shot, kaynak kontrolü; aynı soru ve aynı sahte explain_dict):**
- Örnek 4 ("holdout'taki fraud yakalama oranı"): artık "Bilgi tabanında bu konuda bilgi yok" (`abstained=true`). Model hâlâ üç ilgisiz id eklemişti; servis cevabı temizledi. İlk sürümdeki yanlış sayı ("%3,1") tekrarlanmadı. Tek bir soru ve tek koşudur; genel bir kanıt değildir.
- Örnek 1: "Aristoteles" ifadesi kayboldu, kaynaklar doğru, `grounded=true`. İçerik büyük ölçüde operasyon rehberi ve işlem açıklamasıyla uyumlu (kart yaşı 0, geçmiş 12 işlem açıklamadan geliyor); ilk cümle bozuk kurulmuş. `grounded=true` yalnızca "kaynak id'leri getirilenlerden" demektir, içerik doğruluğu değildir.
- Örnek 2 ve 3: `grounded=true`, içerik bağlamla uyumlu; ikinci örnekte ("neden riskli") modelin "entity'nin geçmiş hareketleri daha az etkilidir" cümlesi KB'de yoktur (hafif uydurma), kaynak kontrolü bunu yakalayamaz.

## Retrieval doğruluğu: hit@k (gerçek indeks)
`tests/rag/retrieval_questions.yaml`: 10 soru, her biri için beklenen bir kural ID'si ve/veya belge türü (veya tek bir chunk id). Sorular sonuçlar görülmeden yazıldı ve sonuçlara bakılarak değiştirilmedi. Arama saf semantiktir (filtresiz, metadata kotası kapalı). Test: `pytest -m ollama -s` (indeks `artifacts/rag/` yoksa veya Ollama kapalıysa atlanır; varsayılan `make test` içinde koşmaz). Eşik (hit@5 >= 0,7) ilk çalıştırmadan önce belirlendi.

| k | hit@k |
|---|---|
| 1 | 0,80 (8/10, yalnızca KB-içi 10 soru) |
| 3 | 1,00 (10/10) |
| 5 | 1,00 (10/10) |

Doğru/yanlış abstain oranları yukarıda (eşik tablosu). hit@1 kaçıran iki soru: "Kart testi şüphesi hangi koşulda tetiklenir?" (beklenen R01 kartı 3. sırada; önce `typologies#card-testing-kart-testi` ve operasyon rehberi geldi) ve "Velocity patlaması kuralı aynı entity için neden bir saatte en fazla bir kez tetiklenir?" (R03 kartı 2. sırada; önce `typologies#velocity-burst-hiz-ve-patlama` geldi). İkisinde de ilk gelen chunk konu olarak ilgili (tipoloji); beklenen kural kartı daha aşağıda kaldı. Ölçüt kural kartını beklediği için bunlar kaçırma sayıldı. Hibrit modda (tetiklenen kural ID'si verilince) R01/R03 kartı kotayla zaten en öne alınır.

Yorum sınırı: 10 soru küçük bir örnektir ve soruları bilgi tabanını yazan geliştirici hazırladı; bu yüzden hit@k iyimser bir tahmindir. Bağımsız bir soru kümesiyle ölçülmedi. Sorgu yeniden yazma, reranker ve çok-chunk cevaplar ölçülmedi.

## Çıktılar
| Yol | İçerik |
|---|---|
| `src/rag/` | `chunker.py`, `kb_builder.py`, `embedder.py`, `llm.py`, `store.py`, `retriever.py`, `prompt.py`, `service.py`, `indexer.py`, `retrieval_eval.py`, `config.py`, `errors.py` |
| `configs/rag.yaml` | modeller, timeout'lar, chunk üst sınırı, retrieval, prompt şablonu, Türkçe feature/operatör etiketleri |
| `knowledge_base/` | elle yazılan 3 belge, `generated/` (otomatik 2 belge), `sources/rule_notes.yaml` |
| `artifacts/rag/` | `index.faiss`, `chunks.jsonl` (gitignore'da; `make rag-index` ile üretilir) |
| `scripts/build_rag_index.py` | KB üret -> chunk'la -> embed et -> kaydet -> örnek sorgu (+ LLM cevabı) |
| `tests/rag/` | 50 birim testi (Ollama'sız) + 1 `ollama` işaretli gerçek retrieval/abstain testi |

Container (yalnızca ekleme): `rag_settings`, `embedder`, `llm_client`, `vector_store`, `retriever`, `prompt_builder`, `rag_service` (hepsi Singleton). `vector_store` ilk çözümlemede indeksi yükler; indeks yoksa `IndexNotBuiltError`. Testlerde `container.embedder.override(...)` ile değiştirilir.

## Komutlar
- Kurulum: `ollama pull bge-m3` ve `ollama pull qwen2.5:7b`, sonra `make rag-index` (LLM'siz: `python scripts/build_rag_index.py --no-llm`; kendi sorunuz için `--question "..."`).
- Gerçek retrieval testi: `.venv/bin/python -m pytest -m ollama -s tests/rag`.
- Varsayılan testler: `make test` (Ollama gerekmez).

## Bilinen sınırlar
- **LLM güvenilirliği (ek turda azaltıldı, çözülmedi):** abstain eşiği ve kaynak kontrolü uydurmayı ve KB-dışı soruları azaltır, içerik doğruluğunu garanti etmez. 7B yerel model talimatı her zaman izlemiyor: bağlam dışı ifade uydurdu (örnek 1) ve bilgi olmayan soruda "bilgi yok" demek yerine ilgisiz bir sayı verdi (örnek 4). Kaynak id'leri her çalıştırmada yazıldı, ama bir id'nin yazılması cevabın doğru olduğunu göstermez (`cited_ids` yalnızca metinde geçen id'leri listeler, içerik doğrulaması yapmaz). Cevap otomasyonu için kullanılmamalıdır.
- **Gecikme:** cevap başına 16-34 sn (7B model, CPU/Apple Silicon, ilk çağrıda model yükleme dahil). API'de zaman aşımı ve eşzamanlılık Adım 10'da ele alınmalı.
- **Bilgi tabanı ölçeği ve dili:** 52 chunk, tek dil (Türkçe). Kural config'indeki `description` alanı İngilizcedir ve kartlarda "(config, İngilizce)" olarak yer alır.
- **`rule_notes.yaml` elle bakım:** kart gövdesi config'ten otomatik üretilir, ama gerekçe ve sınır sayıları elle girilir; `step7.md` yeniden hesaplanırsa güncellenmelidir. Çok sayıda sayı (precision/lift) holdout'a ve post-hoc incelemeye dayanır (K-24, K-25).
- **Hit@k küçük ve yanlı:** 10 soru, soruları KB yazarı hazırladı.
- **Hibrit sıralama basit:** kota tabanlı; RRF veya reranker denenmedi. Aynı kuralı hem tipoloji hem kart anlattığında sıra konu benzerliğine bağlı.
- **Retry yok;** Ollama geçici hatasında tek deneme yapılır.
- **Yedek model denenmedi:** `qwen2.5:3b` bu makinede kurulu değil; yedek yolu yalnızca sahte HTTP ile testlidir.
- **Tek doğruluk kaynağı değil:** KB, kural config'iyle tutarlı üretilir ama `docs/step7.md` ve `docs/step6.md` sayıları kopyadır.

## Bir sonraki adımın girdisi (Adım 9: agent'lar)
- `Container.rag_service().answer(question, explanation=rule_engine_result.explain_dict())`: tetiklenen kural ID'leri `explanation["triggered_rules"]`'dan okunur ve hibrit retrieval'e filtre olur.
- RAG cevabı agent çıktısında "destek bilgisi" olarak etiketlenir; karar kural motorunda kalır (K-33). `abstained` ve `grounded` bayrakları güven düzeyini taşır.
- `RAGAnswer.flags` içindeki `llm_unavailable`, agent'ın retrieval-only yanıta düşmesi için sinyaldir.
- İndeks `make rag-index` ile üretilmeli (`artifacts/rag/` repoda yoktur).
