# Karar Kayıtları

Her önemli karar için: Karar / Alternatifler / Neden seçildi.
Kararları geliştirici verir; Claude Code seçenekleri sunar.

## Şablon

### K-XX: <başlık>
- **Karar:**
- **Alternatifler:**
- **Neden seçildi:**

## Kayıtlar

### K-01: ContextAdjuster arayüzü (batch + online)
- **Karar:** `adjust_batch(df, raw_score) -> DataFrame` ve `adjust_one(record, raw_score) -> AdjustedResult` olmak üzere iki metot; ortak mantık paylaşılır.
- **Alternatifler:** (a) tek `adjust(df, raw_score) -> AdjustedResult` (kural dosyasındaki orijinal hali); (b) tek `adjust(...) -> list[AdjustedResult]` (Adım 0'daki hali).
- **Neden seçildi:** Batch pipeline ve online API aynı kodu kullansın. Batch vektörel çalışır, tek işlem yolu (API) `AdjustedResult` ile açıklamayı döner; iki yol aynı kural mantığına dayandığı için sonuçlar tutarlı kalır.

### K-02: Sabitlerin tek kaynağı
- **Karar:** Split oranı, zaman kolonu, referans tarih ve seed yalnızca `configs/settings.yaml` içinde; kod varsayılanları oradan okur.
- **Alternatifler:** Kodda varsayılan sabit tutmak (çift kaynak).
- **Neden seçildi:** Değer değişince tek yerde değişir; kod ile config'in sessizce ayrışma riski kalkar.

### K-03: SAMPLE_N ile kısmi okuma
- **Karar:** `train_transaction.csv` `nrows=N` ile okunur (dosya TransactionDT'ye göre sıralı), identity okunan TransactionID'lere göre parça parça filtrelenir.
- **Alternatifler:** CSV'yi tam okuyup sıralamak ve kesmek.
- **Neden seçildi:** Geliştirme modunda bellek ve süre N ile orantılı olur. Varsayım: dosya zamana göre sıralı; loader yine de okunan satırları sıralar.

### K-04: RAG chunking stratejisi
- **Karar:** Yapıya duyarlı chunking: markdown `markdown-it-py` ile ağaç yapısına çevrilip başlık sınırlarından bölünür; `rules.yaml`'daki her kural ayrı chunk, kural ID'si metadata'da; uzun bölümler token sınırıyla ikiye ayrılır.
- **Alternatifler:** Sabit boyutlu (token/karakter) chunking, overlap'li.
- **Neden seçildi:** Politika dokümanları başlıklarla yapılandırılmış; başlık sınırı anlam bütünlüğünü korur. Kural bazlı chunk + `rule_id` metadata, tetiklenen kural ID'sine göre filtreli retrieval ve kaynak gösterimini mümkün kılar.

### K-05: Entity proxy
- **Karar:** `card1 + addr1` (adaylarda H); addr1 eksikse NaN ayrı seviye olur. `configs/entity.yaml` içine yazıldı. `D1` anahtara girmez; Adım 3'te iki ayrı feature olarak kullanılır: kart yaşı = `D1` (ilk kullanımdan bu yana geçen gün) ve kart başlangıç günü `D1n` = `floor(TransactionDT/86400) - D1`.
- **D1 yorumu testi (tam veri, `scripts/check_d1_semantics.py`, `reports/profile/d1_semantics.csv`):** "D1 = önceki işlemden beri gün" hipotezi şansın üzerinde değil (|fark - D1| <= 1 oranı %34,4; D1 entity içinde karıştırılınca %33,4). "D1 = kart başlangıcından beri" hipotezi tutuyor: (H, D1n) çifti satırların %63,2'sinde daha önce görülmüş, karıştırılmış D1 ile %33,0. D1n'in H içinde değişmesi (d1n_constancy: işlemlerin ~%96'sı aralığı > 1 gün olan entity'lerde) H'nin birden fazla kartı birleştirmesinden kaynaklanır; her kartın D1n'i sabittir. Bu yorum kanıtlanmış değil, veriyle desteklenen bir varsayımdır (gerçek kart no yok).
- **Alternatifler:** A (`card1`), I (`card1+addr1+D1n`), J (`I + P_emaildomain`).
- **Neden seçildi:** I entity'leri daha homojen yapıyor (log-tutar std 0,35 vs 0,59) ama holdout satırlarının %56'sında entity fit'te görülmüyor; geçmiş tabanlı feature'lar soğuk başlar. H tüm satırları kapsar (tanımsız satır %0) ve holdout'ta %95,8 oranında tanınır. A daha basit ama birden çok kartı birleştirir (max 14.932 işlem). Entity seçimi etiket kullanılmadan, yalnızca sayısal karşılaştırmayla yapıldı.

(Sıradaki kararlar: anomali yöntemleri ve ağırlıkları.)
