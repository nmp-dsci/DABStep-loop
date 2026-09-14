"""`make data`: fetch the benchmark from the Hub into `data/`.

Context files land in `data/context/` (gitignored — payments.csv alone is 23 MB).
Task files are copied to `data/tasks/` and committed, and a committed sample of
the context (`data/samples/`) is regenerated so CI, tests and the demo image
have real data without the download.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

from dabstep_loop.config import CONTEXT_DIR, DATA_DIR, HF_DATASET, SAMPLES_DIR, TASKS_DIR

SAMPLE_ROWS = 500
CONTEXT_FILES = [
    "payments.csv",
    "fees.json",
    "manual.md",
    "merchant_data.json",
    "acquirer_countries.csv",
    "merchant_category_codes.csv",
    "payments-readme.md",
]


def download(force: bool = False) -> Path:
    """Download the dataset snapshot and lay it out under data/."""
    local = DATA_DIR / ".hf"
    snapshot_download(
        repo_id=HF_DATASET,
        repo_type="dataset",
        allow_patterns=["data/context/*", "data/tasks/*"],
        local_dir=local,
        force_download=force,
    )
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    for name in CONTEXT_FILES:
        shutil.copyfile(local / "data" / "context" / name, CONTEXT_DIR / name)
    for name in ("dev.jsonl", "all.jsonl"):
        shutil.copyfile(local / "data" / "tasks" / name, TASKS_DIR / name)
    write_samples()
    return CONTEXT_DIR


def write_samples(rows: int = SAMPLE_ROWS) -> Path:
    """Copy every small context file and the first `rows` of payments.csv."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name in CONTEXT_FILES:
        if name == "payments.csv":
            continue
        shutil.copyfile(CONTEXT_DIR / name, SAMPLES_DIR / name)
    with (
        (CONTEXT_DIR / "payments.csv").open(newline="", encoding="utf-8") as src,
        (SAMPLES_DIR / "payments.csv").open("w", newline="", encoding="utf-8") as dst,
    ):
        reader = csv.reader(src)
        writer = csv.writer(dst)
        for i, row in enumerate(reader):
            if i > rows:
                break
            writer.writerow(row)
    return SAMPLES_DIR
