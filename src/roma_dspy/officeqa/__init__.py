"""Canonical OfficeQA primitives shared across ROMA runtime and benchmark code."""

from .dataset import (
    DEFAULT_DATA_DIR,
    OFFICEQA_FULL_URL,
    OFFICEQA_PRO_URL,
    download_officeqa_data,
    load_officeqa_benchmark,
    load_source_documents,
    resolve_officeqa_transformed_dir,
)
from .modules import OfficeQARLMExecutor
from .runtime import (
    OfficeQACorpusLayout,
    OfficeQARuntimeResult,
    OfficeQARuntimeRunner,
    resolve_officeqa_corpus_layout,
)
from .scoring import (
    check_text_overlap,
    detect_unit_in_context,
    extract_final_answer,
    extract_officeqa_answer,
    extract_numbers_with_context,
    has_significant_text,
    is_likely_year,
    normalize_text,
    score_answer,
)
from .types import OfficeQAQuestion

__all__ = [
    "DEFAULT_DATA_DIR",
    "OFFICEQA_FULL_URL",
    "OFFICEQA_PRO_URL",
    "OfficeQACorpusLayout",
    "OfficeQAQuestion",
    "OfficeQARLMExecutor",
    "OfficeQARuntimeResult",
    "OfficeQARuntimeRunner",
    "check_text_overlap",
    "detect_unit_in_context",
    "download_officeqa_data",
    "extract_final_answer",
    "extract_officeqa_answer",
    "extract_numbers_with_context",
    "has_significant_text",
    "is_likely_year",
    "load_officeqa_benchmark",
    "load_source_documents",
    "normalize_text",
    "resolve_officeqa_corpus_layout",
    "resolve_officeqa_transformed_dir",
    "score_answer",
]
