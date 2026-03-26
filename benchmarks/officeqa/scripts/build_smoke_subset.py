#!/usr/bin/env python3
"""Build a curated OfficeQA smoke subset for fast end-to-end verification."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from benchmarks.officeqa.scripts.question_typing import classify_question

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data" / "officeqa"
SOURCE_CSV = DATA_DIR / "officeqa_pro.csv"
OUTPUT_CSV = DATA_DIR / "officeqa_smoke.csv"
OUTPUT_MANIFEST = DATA_DIR / "officeqa_smoke_manifest.json"

SMOKE_UIDS = [
    "UID0001",  # single-document aggregation
    "UID0007",  # geometric mean
    "UID0012",  # fiscal-year reasoning
    "UID0013",  # unit-sensitive regression
    "UID0017",  # multi-value numeric extraction
    "UID0025",  # multi-document difference
    "UID0028",  # direct lookup across two documents
    "UID0084",  # open-form statistical forecast error
]


def build_smoke_subset() -> tuple[Path, Path]:
    df = pd.read_csv(SOURCE_CSV)
    subset = df[df["uid"].isin(SMOKE_UIDS)].copy()

    missing = [uid for uid in SMOKE_UIDS if uid not in set(subset["uid"])]
    if missing:
        raise ValueError(f"Missing OfficeQA smoke UIDs in source CSV: {missing}")

    subset["uid"] = pd.Categorical(subset["uid"], categories=SMOKE_UIDS, ordered=True)
    subset = subset.sort_values("uid").reset_index(drop=True)
    subset["question_type"] = subset["question"].apply(classify_question)
    subset["source_file_count"] = subset["source_files"].fillna("").apply(
        lambda value: len([line for line in str(value).splitlines() if line.strip()])
    )
    subset.to_csv(OUTPUT_CSV, index=False)

    manifest = {
        "name": "officeqa_smoke",
        "source_csv": str(SOURCE_CSV.relative_to(PROJECT_ROOT)),
        "output_csv": str(OUTPUT_CSV.relative_to(PROJECT_ROOT)),
        "size": len(subset),
        "uids": SMOKE_UIDS,
        "question_types": subset["question_type"].value_counts().sort_index().to_dict(),
        "questions": [
            {
                "uid": row.uid,
                "question_type": row.question_type,
                "source_file_count": int(row.source_file_count),
                "source_files": row.source_files,
            }
            for row in subset.itertuples(index=False)
        ],
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return OUTPUT_CSV, OUTPUT_MANIFEST


if __name__ == "__main__":
    csv_path, manifest_path = build_smoke_subset()
    print(f"Wrote {csv_path}")
    print(f"Wrote {manifest_path}")
