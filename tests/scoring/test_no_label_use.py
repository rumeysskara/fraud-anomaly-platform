"""The scoring path must not read the label (isFraud only lives in loader / evaluation)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_detection_and_scoring_never_mention_the_label():
    for folder in ("src/detection", "src/scoring"):
        for path in (ROOT / folder).glob("*.py"):
            assert "isFraud" not in path.read_text(), path


def test_run_scoring_reads_label_only_in_evaluate_holdout():
    text = (ROOT / "scripts/run_scoring.py").read_text()
    head, _, tail = text.partition("def evaluate_holdout")
    body, _, rest = tail.partition("\ndef main")
    assert "load_data" in body and "load_data" not in head and "load_data" not in rest
