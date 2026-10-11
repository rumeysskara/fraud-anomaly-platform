# Fraud & Anomaly Detection Platform

IEEE-CIS verisi üzerinde çok katmanlı anomali tespiti, context-aware skor düzeltme,
konfigüre edilebilir kural motoru, local-LLM RAG ve multi-agent orkestrasyon; FastAPI ile servisleştirilir.

> Geliştirmede Claude Code kullanılmıştır; mimari ve iş kuralı kararları geliştiriciye aittir. Karar kayıtları: docs/decisions.md

## Kurulum
```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install
```

## Veri
`train_transaction.csv` ve `train_identity.csv` dosyalarını `data/raw/` altına koyun
(Kaggle IEEE-CIS Fraud Detection). Veri repoya eklenmez.
Hızlı geliştirme için: `SAMPLE_N=50000 make pipeline` (zamana göre ilk N satır).

## Ollama
(Adım 8 sonrası doldurulacak: Ollama kurulumu, model indirme komutları.)

## Çalıştırma
```bash
make pipeline      # tüm adımlar (henüz yazılmamış adımlar atlanır)
make api           # FastAPI (Adım 10)
```

## Testler
```bash
make test
make lint
```

## Mimari
Katman yönü: api -> agents -> (rag, rules, context, scoring, detection) -> features -> data.
Ortak arayüzler: `src/core/interfaces.py`; DI: `src/container.py`; sabitler: `configs/settings.yaml`.

## Doküman
- Adım dokümanları: `docs/step*.md`
- Karar kayıtları: `docs/decisions.md`
- Teknik doküman: `docs/technical_doc.md` (son adımda)
