"""Shared OfficeQA dataset loading and corpus utilities."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Optional

import pandas as pd

from .types import OfficeQAQuestion


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "officeqa"
OFFICEQA_SUBSET_FILES = {
    "pro": "officeqa_pro.csv",
    "full": "officeqa_full.csv",
    "smoke": "officeqa_smoke.csv",
    "bench5": "officeqa_bench5.csv",
}
OFFICEQA_REMOTE_URLS = {
    "pro": "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_pro.csv",
    "full": "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_full.csv",
}
OFFICEQA_PRO_URL = OFFICEQA_REMOTE_URLS["pro"]
OFFICEQA_FULL_URL = OFFICEQA_REMOTE_URLS["full"]


def _default_transformed_candidates() -> list[Path]:
    return [
        DEFAULT_DATA_DIR / "transformed",
        REPO_ROOT / "data" / "treasury_bulletins_transformed",
        Path.home() / "officeqa" / "treasury_bulletins_parsed" / "transformed",
    ]


def _looks_like_transformed_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    if path.name == "transformed":
        return True
    return any(path.glob("*.txt"))


def resolve_officeqa_transformed_dir(
    corpus_dir: Optional[Path | str] = None,
) -> Optional[Path]:
    """Resolve a usable transformed-text directory for OfficeQA."""
    candidates: list[Path] = []
    if corpus_dir is not None:
        candidates.append(Path(corpus_dir).expanduser())
    candidates.extend(_default_transformed_candidates())

    for candidate in candidates:
        candidate = candidate.resolve()
        if not candidate.exists():
            continue
        if candidate.is_dir() and (candidate / "transformed").is_dir():
            return (candidate / "transformed").resolve()
        if _looks_like_transformed_dir(candidate):
            return candidate
    return None


def ensure_officeqa_subset_available(
    subset: str,
    data_dir: Optional[Path | str] = None,
) -> Path:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = OFFICEQA_SUBSET_FILES[subset]
    path = data_dir / filename

    url = OFFICEQA_REMOTE_URLS.get(subset)
    if url and not path.exists():
        urllib.request.urlretrieve(url, path)

    return data_dir


def download_officeqa_data(data_dir: Optional[Path | str] = None) -> Path:
    """Backward-compatible downloader for the standard OfficeQA subsets."""
    ensure_officeqa_subset_available("pro", data_dir=data_dir)
    ensure_officeqa_subset_available("full", data_dir=data_dir)
    return Path(data_dir or DEFAULT_DATA_DIR).expanduser().resolve()


def load_officeqa_benchmark(
    subset: str = "pro",
    limit: Optional[int] = None,
    data_dir: Optional[Path | str] = None,
) -> list[OfficeQAQuestion]:
    if subset not in OFFICEQA_SUBSET_FILES:
        raise ValueError(f"Unsupported OfficeQA subset: {subset}")

    resolved_data_dir = ensure_officeqa_subset_available(subset=subset, data_dir=data_dir)
    csv_path = resolved_data_dir / OFFICEQA_SUBSET_FILES[subset]
    if not csv_path.exists():
        raise FileNotFoundError(f"OfficeQA dataset not found at {csv_path}")

    df = pd.read_csv(csv_path)
    questions = [
        OfficeQAQuestion(
            uid=str(row["uid"]),
            question=str(row["question"]),
            answer=str(row["answer"]),
            source_docs=str(row.get("source_docs", "")),
            source_files=str(row.get("source_files", "")),
            difficulty=str(row.get("difficulty", "hard")),
        )
        for _, row in df.iterrows()
    ]

    if limit is not None:
        questions = questions[:limit]
    return questions


def load_source_documents(
    source_files: str,
    corpus_dir: Optional[Path | str] = None,
) -> str:
    """Load Treasury Bulletin transformed text for a question's source files."""
    transformed_dir = resolve_officeqa_transformed_dir(corpus_dir)
    if not transformed_dir:
        return ""

    documents = []
    for filename in re.split(r"[,\n]+", source_files):
        filename = filename.strip()
        if not filename:
            continue
        filepath = transformed_dir / filename
        if filepath.exists():
            documents.append(filepath.read_text(errors="replace"))
    return "\n\n---\n\n".join(documents)
