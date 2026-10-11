---
paths:
  - "**/*.py"
  - "pyproject.toml"
---

# Python Stil Kuralları

- Python 3.11. Type hint zorunlu (public fonksiyon ve sınıflarda).
- Public fonksiyon/sınıflarda kısa docstring (ne yapar, girdi, çıktı).
- Format: black (line-length 100) + ruff; ayarlar pyproject.toml'da. Bitirmeden önce `make lint`.
- Modül başına tek sorumluluk; dosya 400 satırı geçmesin.
- Sihirli sayı yok: eşikler, ağırlıklar, sabitler `configs/*.yaml` içinde.
- Print yerine `logging` (modül başına `logger = logging.getLogger(__name__)`).
- Rastgelelik: her yerde seed=42 (numpy, sklearn, faiss, random).
- Büyük DataFrame: dtype downcast, gereksiz kopya yok, ara çıktılar parquet.
- Notebook yok. Analizler `scripts/` altında çalıştırılabilir .py olarak.
- Testler: `tests/` altında, modül yapısını yansıtır (tests/rules/test_engine.py gibi).
  Her modül için en az bir pytest; küçük sentetik DataFrame ile çalışmalı
  (gerçek 590k satırlık veriye ve çalışan Ollama'ya bağımlı olmasın).
