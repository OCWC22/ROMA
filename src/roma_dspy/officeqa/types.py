"""Shared OfficeQA data models."""

from dataclasses import dataclass


@dataclass
class OfficeQAQuestion:
    """A single OfficeQA benchmark question."""

    uid: str
    question: str
    answer: str
    source_docs: str = ""
    source_files: str = ""
    difficulty: str = "hard"
    question_type: str = ""
