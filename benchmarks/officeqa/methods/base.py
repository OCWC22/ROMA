"""
Shared infrastructure for OfficeQA benchmark.

Provides: SolverResult schema, BaseSolver ABC, LLMClient, scoring, data loading,
train/val/test splits, corpus loading.
"""

import json
import re
import subprocess
import sys
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ============================================================================
# PATHS
# ============================================================================

BENCHMARKS_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCHMARKS_ROOT.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "officeqa"
OFFICEQA_PRO_URL = "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_pro.csv"
OFFICEQA_FULL_URL = "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_full.csv"


# ============================================================================
# DATA TYPES
# ============================================================================

@dataclass
class OfficeQAQuestion:
    """A single OfficeQA benchmark question."""
    uid: str
    question: str
    answer: str
    source_docs: str = ""
    source_files: str = ""
    difficulty: str = "hard"
    question_type: str = ""  # filled by question_typing


@dataclass
class SolverResult:
    """Standard result from any solver. Every method returns this."""
    method: str
    predicted: str
    expected: str
    score: float = 0.0
    duration: float = 0.0
    used_context: bool = False
    raw_output: str = ""
    final_answer: str = ""
    trace: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class BaseSolver(ABC):
    """Every benchmark method implements this."""
    name: str = "base"

    @abstractmethod
    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        ...


# ============================================================================
# LLM CLIENT (CLI / API)
# ============================================================================

@dataclass
class CLIResult:
    success: bool
    output: str
    error: str = ""
    duration: float = 0.0


class LLMClient:
    """LLM client using Claude CLI or Codex CLI. Falls back to Anthropic API."""

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude", timeout: int = 120):
        self.model = model
        self.cli = cli
        self.timeout = timeout
        self._api_client = None

        try:
            subprocess.run([self.cli, "--version"], capture_output=True, timeout=5)
            self._cli_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._cli_available = False

        if not self._cli_available:
            try:
                import anthropic
                self._api_client = anthropic.Anthropic()
            except Exception:
                pass

    def call(self, prompt: str, system: str = "", model: str = None) -> CLIResult:
        model = model or self.model
        start = time.time()

        if self._cli_available:
            return self._call_cli(prompt, system, model, start)
        elif self._api_client:
            return self._call_api(prompt, system, model, start)
        else:
            return CLIResult(
                success=False, output="",
                error=f"Neither {self.cli} CLI nor Anthropic API available",
                duration=time.time() - start,
            )

    def _call_cli(self, prompt: str, system: str, model: str, start: float) -> CLIResult:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        if self.cli == "codex":
            cmd = ["codex", "--model", model, "--quiet", full_prompt]
        else:
            cmd = ["claude", "--print", "--model", model, full_prompt]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            return CLIResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr if result.returncode != 0 else "",
                duration=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return CLIResult(success=False, output="", error="TIMEOUT", duration=self.timeout)
        except Exception as e:
            return CLIResult(success=False, output="", error=str(e), duration=time.time() - start)

    def _call_api(self, prompt: str, system: str, model: str, start: float) -> CLIResult:
        try:
            messages = [{"role": "user", "content": prompt}]
            kwargs = {"model": model, "max_tokens": 512, "messages": messages}
            if system:
                kwargs["system"] = system
            resp = self._api_client.messages.create(**kwargs)
            return CLIResult(
                success=True,
                output=resp.content[0].text.strip(),
                duration=time.time() - start,
            )
        except Exception as e:
            return CLIResult(success=False, output="", error=str(e), duration=time.time() - start)


# ============================================================================
# HELPERS
# ============================================================================

def resolve_litellm_model(model: str) -> str:
    """Ensure model string has provider prefix for litellm."""
    return model if "/" in model else f"anthropic/{model}"


# ============================================================================
# OFFICEQA SCORING (from databricks/officeqa/reward.py)
# ============================================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace('\u2212', '-')


def extract_numbers_with_context(text: str) -> list:
    if not text:
        return []
    text = normalize_text(text)
    text_no_commas = re.sub(
        r'\d{1,3}(?:,\d{3})+(?:\.\d+)?',
        lambda m: m.group().replace(',', ''),
        text,
    )
    results = []
    for match in re.finditer(r'-?\d+\.?\d*%?', text_no_commas):
        matched_text = match.group()
        if not matched_text or matched_text == '-':
            continue
        has_percent = matched_text.endswith('%')
        num_text = matched_text.rstrip('%')
        try:
            num = float(num_text)
        except ValueError:
            continue
        start = max(0, match.start() - 20)
        end = min(len(text_no_commas), match.end() + 20)
        context = text_no_commas[start:end].lower()
        results.append((num, context, has_percent, num_text.startswith('-')))
    return results


def detect_unit_in_context(context: str):
    ctx = context.lower()
    if re.search(r'\btrillions?\b', ctx):
        return ('trillion', 1e12)
    if re.search(r'\bbillions?\b', ctx):
        return ('billion', 1e9)
    if re.search(r'\bmillions?\b', ctx):
        return ('million', 1e6)
    if re.search(r'\bthousands?\b', ctx):
        return ('thousand', 1e3)
    return (None, 1.0)


def is_likely_year(num: float) -> bool:
    return 1900 <= num <= 2100 and num == int(num)


def has_significant_text(text: str):
    if not text:
        return False, ""
    cleaned = normalize_text(text).lower()
    cleaned = re.sub(r'-?\d+\.?\d*%?', '', cleaned)
    cleaned = re.sub(r'[,]', '', cleaned)
    for unit in ['trillion', 'trillions', 'billion', 'billions', 'million', 'millions',
                 'thousand', 'thousands', 'hundred', 'hundreds', 'percent', 'percentage', '%']:
        cleaned = re.sub(r'\b' + unit + r'\b', '', cleaned)
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return len(cleaned) >= 2, cleaned


def check_text_overlap(gt_text: str, pred_text: str):
    if not gt_text or not pred_text:
        return False, "Empty text"
    gt_has, gt_cleaned = has_significant_text(gt_text)
    pred_has, pred_cleaned = has_significant_text(pred_text)
    if not gt_has:
        return True, "GT is purely numeric"
    if not pred_has:
        return False, f"GT has text '{gt_cleaned}' but prediction is purely numeric"
    if gt_cleaned in pred_cleaned:
        return True, f"Text match: '{gt_cleaned}'"
    if pred_cleaned in gt_cleaned:
        return True, f"Text match: '{pred_cleaned}'"
    return False, f"Text mismatch: GT='{gt_cleaned}', Pred='{pred_cleaned}'"


def extract_final_answer(text: str) -> str:
    if not text:
        return ""
    match = re.search(r'<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Also try ANSWER: format
    match = re.search(r'ANSWER:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def score_answer(ground_truth: str, predicted: str, tolerance: float = 0.0) -> float:
    """OfficeQA official fuzzy matching. Returns 1.0 if correct, 0.0 otherwise."""
    if not ground_truth or not predicted:
        return 0.0

    predicted = extract_final_answer(predicted)

    gt_numbers = extract_numbers_with_context(ground_truth)
    pred_numbers = extract_numbers_with_context(predicted)

    gt_nums = [(n, c) for n, c, _, _ in gt_numbers]
    pred_nums = [(n, c) for n, c, _, _ in pred_numbers]

    if gt_nums and pred_nums:
        if len(gt_nums) == 1:
            gt_val, _gt_ctx = gt_nums[0]
            gt_base = gt_val
            gt_has_text, _ = has_significant_text(ground_truth)
            should_filter_years = not (is_likely_year(gt_val) or gt_has_text)

            for pred_val, _pred_ctx in pred_nums:
                if should_filter_years and is_likely_year(pred_val):
                    continue
                pred_base = pred_val
                if gt_base == 0:
                    if pred_base == 0:
                        tm, _ = check_text_overlap(ground_truth, predicted)
                        if tm:
                            return 1.0
                    continue
                diff = abs(gt_base - pred_base) / abs(gt_base)
                if diff <= tolerance:
                    tm, _ = check_text_overlap(ground_truth, predicted)
                    if tm:
                        return 1.0
            return 0.0
        else:
            pred_non_years = [(n, c) for n, c in pred_nums
                              if not is_likely_year(n) or any(is_likely_year(g) for g, _ in gt_nums)]
            matched = 0
            for gv, _gc in gt_nums:
                for pv, _pc in pred_non_years:
                    if gv == 0 and pv == 0:
                        tm, _ = check_text_overlap(ground_truth, predicted)
                        if tm:
                            matched += 1
                            break
                    elif gv != 0 and abs(gv - pv) / abs(gv) <= tolerance:
                        tm, _ = check_text_overlap(ground_truth, predicted)
                        if tm:
                            matched += 1
                            break
            return 1.0 if matched == len(gt_nums) else 0.0

    # Text comparison
    gt_clean = ground_truth.strip().lower().strip('"\'')
    pred_clean = predicted.strip().lower().strip('"\'')
    gt_clean = re.sub(r'\([^)]*\)', '', gt_clean).strip()
    pred_clean = re.sub(r'\([^)]*\)', '', pred_clean).strip()
    if gt_clean in pred_clean or gt_clean == pred_clean:
        return 1.0
    return 0.0


# ============================================================================
# DATA LOADING
# ============================================================================

def download_officeqa_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in [("officeqa_pro.csv", OFFICEQA_PRO_URL),
                       ("officeqa_full.csv", OFFICEQA_FULL_URL)]:
        path = DATA_DIR / name
        if not path.exists():
            print(f"Downloading {name}...")
            urllib.request.urlretrieve(url, path)
            print(f"  Saved to {path}")


def load_officeqa_benchmark(
    subset: str = "pro",
    limit: Optional[int] = None,
) -> List[OfficeQAQuestion]:
    download_officeqa_data()
    csv_path = DATA_DIR / f"officeqa_{subset}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"OfficeQA dataset not found at {csv_path}")

    df = pd.read_csv(csv_path)
    questions = []
    for _, row in df.iterrows():
        questions.append(OfficeQAQuestion(
            uid=str(row["uid"]),
            question=str(row["question"]),
            answer=str(row["answer"]),
            source_docs=str(row.get("source_docs", "")),
            source_files=str(row.get("source_files", "")),
            difficulty=str(row.get("difficulty", "hard")),
        ))

    if limit is not None:
        questions = questions[:limit]
    return questions


def load_source_documents(source_files: str, corpus_dir: Optional[Path] = None) -> str:
    """Load Treasury Bulletin source documents. Returns concatenated text or empty string."""
    if not corpus_dir:
        for candidate in [
            PROJECT_ROOT / "data" / "officeqa" / "transformed",
            PROJECT_ROOT / "data" / "treasury_bulletins_transformed",
            Path.home() / "officeqa" / "treasury_bulletins_parsed" / "transformed",
        ]:
            if candidate.exists():
                corpus_dir = candidate
                break

    if not corpus_dir or not corpus_dir.exists():
        return ""

    documents = []
    filenames = re.split(r'[,\n]+', source_files)
    for filename in filenames:
        filename = filename.strip()
        if not filename:
            continue
        filepath = corpus_dir / filename
        if filepath.exists():
            documents.append(filepath.read_text(errors="replace"))

    return "\n\n---\n\n".join(documents)


# ============================================================================
# DATA SPLITS
# ============================================================================

def make_splits(
    questions: List[OfficeQAQuestion],
    train_size: int = 20,
    val_size: int = 10,
    seed: int = 42,
) -> Tuple[List[OfficeQAQuestion], List[OfficeQAQuestion], List[OfficeQAQuestion]]:
    """
    Split questions into train / val / test.
    Returns (train, val, test). Test is everything left over.
    """
    import random
    rng = random.Random(seed)
    shuffled = list(questions)
    rng.shuffle(shuffled)

    train = shuffled[:train_size]
    val = shuffled[train_size:train_size + val_size]
    test = shuffled[train_size + val_size:]

    return train, val, test


def save_splits(train, val, test, output_dir: Path):
    """Save UID lists so splits are reproducible."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, qs in [("train_uids.json", train), ("val_uids.json", val), ("test_uids.json", test)]:
        with open(output_dir / name, "w") as f:
            json.dump([q.uid for q in qs], f, indent=2)


# ============================================================================
# SEED PROMPT
# ============================================================================

OFFICEQA_SEED_PROMPT = """You are an expert analyst of U.S. Treasury Bulletins (1939-2025).
Answer with ONLY the value. No explanation. No refusal.

RULES:
1. If a table header says "in millions of dollars", report the base number as-is (e.g., 2,602 not 2,602,000,000).
2. Fiscal year conventions:
   - Before FY1977: Jul 1 of prior year to Jun 30 (e.g., FY1975 = Jul 1974 - Jun 1975)
   - FY1977 onward: Oct 1 of prior year to Sep 30 (e.g., FY2020 = Oct 2019 - Sep 2020)
   - Transition Quarter (TQ/1976): Jul 1 - Sep 30, 1976
3. Extract exact values from tables. Only calculate if explicitly asked.
4. For sums: add all individual values. For geometric mean: GM = (y1*y2*...*yn)^(1/n).
5. Match the format of the original table.
6. ALWAYS provide your best answer as a single value."""
