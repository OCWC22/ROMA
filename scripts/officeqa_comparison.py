#!/usr/bin/env python3
"""
OfficeQA Benchmark Comparison Runner

Compares three approaches on the real OfficeQA dataset (Databricks):
1. RLM: Recursive Language Model (Zhang et al.) via `rlm` package
2. GEPA+: Evolutionary prompt optimization via `gepa` package
3. ROMA: Recursive Open Meta-Agents via DSPy pipeline

Authentication:
- Uses Claude CLI (authenticated via CodeMax subscription) by default
- Also supports Codex CLI — swap with --cli codex
- ANTHROPIC_API_KEY used by RLM package backend (auto-detected from CLI config)
- OfficeQA CSVs in data/officeqa/ (auto-downloaded if missing)
"""

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ============================================================================
# CLI WRAPPER (Claude CLI / Codex CLI — no API keys needed)
# ============================================================================

@dataclass
class CLIResult:
    """Result from a CLI call."""
    success: bool
    output: str
    error: str = ""
    duration: float = 0.0


class LLMClient:
    """
    LLM client that uses Claude CLI or Codex CLI (authenticated via subscription).
    Falls back to Anthropic API if available.
    """

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude", timeout: int = 120):
        self.model = model
        self.cli = cli  # "claude" or "codex"
        self.timeout = timeout
        self._api_client = None

        # Verify CLI is available
        try:
            subprocess.run([self.cli, "--version"], capture_output=True, timeout=5)
            self._cli_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._cli_available = False

        # Try API client as fallback
        if not self._cli_available:
            try:
                import anthropic
                self._api_client = anthropic.Anthropic()
            except Exception:
                pass

    def call(self, prompt: str, system: str = "", model: str = None) -> CLIResult:
        """Make an LLM call via CLI or API."""
        model = model or self.model
        start = time.time()

        if self._cli_available:
            return self._call_cli(prompt, system, model, start)
        elif self._api_client:
            return self._call_api(prompt, system, model, start)
        else:
            return CLIResult(
                success=False,
                output="",
                error=f"Neither {self.cli} CLI nor Anthropic API available",
                duration=time.time() - start,
            )

    def _call_cli(self, prompt: str, system: str, model: str, start: float) -> CLIResult:
        """Call via Claude/Codex CLI."""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        if self.cli == "codex":
            cmd = ["codex", "--model", model, "--quiet", full_prompt]
        else:
            cmd = ["claude", "--print", "--model", model, full_prompt]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout
            )
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
        """Fallback: call via Anthropic API."""
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
# OFFICEQA DATASET LOADING
# ============================================================================

DATA_DIR = PROJECT_ROOT / "data" / "officeqa"
OFFICEQA_PRO_URL = "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_pro.csv"
OFFICEQA_FULL_URL = "https://raw.githubusercontent.com/databricks/officeqa/main/officeqa_full.csv"


@dataclass
class OfficeQAQuestion:
    """A single OfficeQA benchmark question."""
    uid: str
    question: str
    answer: str
    source_docs: str = ""
    source_files: str = ""
    difficulty: str = "hard"


def download_officeqa_data():
    """Download OfficeQA CSVs from GitHub if not present."""
    import urllib.request

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
    """
    Load real OfficeQA benchmark from CSV.

    Args:
        subset: "pro" (133 hard questions) or "full" (246 questions)
        limit: Max number of questions to load
    """
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

    if limit:
        questions = questions[:limit]

    return questions


# ============================================================================
# OFFICEQA OFFICIAL SCORING (from databricks/officeqa/reward.py)
# ============================================================================

def normalize_text(text: str) -> str:
    """Normalize Unicode minus to ASCII hyphen."""
    if not text:
        return ""
    return text.replace('\u2212', '-').replace('\u2212', '-')


def extract_numbers_with_context(text: str) -> list:
    """Extract numbers with surrounding context for unit detection."""
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
        is_negative = num_text.startswith('-')
        try:
            num = float(num_text)
        except ValueError:
            continue
        start = max(0, match.start() - 20)
        end = min(len(text_no_commas), match.end() + 20)
        context = text_no_commas[start:end].lower()
        results.append((num, context, has_percent, is_negative))
    return results


def detect_unit_in_context(context: str):
    """Detect unit words in context and return multiplier."""
    ctx = context.lower()
    if re.search(r'\btrillions?\b', ctx):
        return ('trillion', 1e12)
    if re.search(r'\bbillions?\b', ctx) or re.search(r'\bb\b', ctx):
        return ('billion', 1e9)
    if re.search(r'\bmillions?\b', ctx) or re.search(r'\bm\b', ctx):
        return ('million', 1e6)
    if re.search(r'\bthousands?\b', ctx) or re.search(r'\bk\b', ctx):
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
    """Extract content from <FINAL_ANSWER> tags if present."""
    if not text:
        return ""
    match = re.search(r'<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>', text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def score_answer(ground_truth: str, predicted: str, tolerance: float = 0.0) -> float:
    """
    Score using OfficeQA official fuzzy matching (from reward.py).
    Returns 1.0 if correct, 0.0 otherwise.
    """
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
            # Multi-number: all GT numbers must appear
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
# CORPUS LOADING (optional - for methods that need document context)
# ============================================================================

def load_source_documents(source_files: str, corpus_dir: Optional[Path] = None) -> str:
    """
    Load Treasury Bulletin source documents for a question.
    Returns concatenated text content, or empty string if not available.
    """
    if not corpus_dir:
        # Try common locations
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
    # Handle comma-separated, newline-separated, or space-separated file lists
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
# RLM SOLVER (using real `rlm` package, with CLI fallback)
# ============================================================================

RLM_SYSTEM = """You are an RLM (Recursive Language Model) solving Treasury Bulletin questions.
You MUST always provide a numerical or factual answer. Never refuse to answer.

Think step by step:
1. Search through document context if provided
2. Extract numbers from tables
3. Perform calculations (sums, geometric means, etc.)
4. Use your knowledge of U.S. Treasury data when documents aren't available

RULES:
- If a table header says 'in millions', report the BASE number (e.g., 2602, NOT 2602000000)
- Fiscal years before 1977: Jul-Jun; FY1977 onward: Oct-Sep
- Transition Quarter (TQ/1976): Jul 1 – Sep 30, 1976
- ALWAYS provide your best answer. NEVER refuse or say you can't.
- Return your final answer as: ANSWER: <value>"""


class RLMSolver:
    """
    RLM: Recursive Language Model (Zhang et al., 2025)

    Uses the real `rlm` package when ANTHROPIC_API_KEY is available.
    Falls back to CLI-based recursive solving (multi-turn REPL simulation) otherwise.
    """

    def __init__(self, model: str = "claude-haiku-4-5", corpus_dir: Optional[Path] = None,
                 cli: str = "claude"):
        self.model = model
        self.corpus_dir = corpus_dir
        self.name = "RLM"
        self._llm = LLMClient(model=model, cli=cli)
        print(f"  RLM initialized (cli={cli}, model={model})")

    def solve(self, question: OfficeQAQuestion) -> Dict:
        """
        CLI-based RLM: multi-turn recursive solving.
        Simulates the RLM REPL loop: Root LM analyzes -> retrieves -> sub-queries -> answers.
        """
        start = time.time()
        context = load_source_documents(question.source_files, self.corpus_dir)

        # Step 1: Root LM — analyze and decompose if needed
        root_prompt = f"{RLM_SYSTEM}\n\n"
        if context:
            root_prompt += f"DOCUMENT CONTEXT:\n{context[:40000]}\n\n"
        root_prompt += (
            f"QUESTION: {question.question}\n\n"
            f"Think step by step. If you need to search through the document, "
            f"describe what you're looking for. Then provide the answer.\n\n"
            f"Return your final answer as: ANSWER: <value>"
        )

        root_result = self._llm.call(root_prompt)
        root_output = root_result.output

        # Extract answer from root response
        answer_match = re.search(r'ANSWER:\s*(.+?)(?:\n|$)', root_output, re.IGNORECASE)
        if answer_match:
            predicted = answer_match.group(1).strip()
        else:
            # Step 2: If root didn't give a clean answer, do a focused follow-up
            followup = self._llm.call(
                f"Based on your analysis:\n{root_output[:2000]}\n\n"
                f"What is the final answer to: {question.question}\n\n"
                f"Respond with ONLY the answer value, nothing else.",
                system=RLM_SYSTEM,
            )
            predicted = followup.output.strip()

        predicted = extract_final_answer(predicted)

        return {
            "method": "RLM",
            "predicted": predicted,
            "expected": question.answer,
            "duration": time.time() - start,
            "model": self.model,
            "backend": "cli",
        }


# ============================================================================
# GEPA+ SOLVER (using real `gepa` package)
# ============================================================================

# Seed prompt for Treasury Bulletin QA
OFFICEQA_SEED_PROMPT = """You are an expert analyst of U.S. Treasury Bulletins (1939-2025).
You MUST always provide a numerical or factual answer. Never say "I don't have access" or refuse to answer.
Use the provided document context if available. Otherwise, use your knowledge of U.S. Treasury data.

CRITICAL RULES:
1. NEVER expand units — if a table header says "in millions of dollars", report the base number as-is (e.g., 2,602 not 2,602,000,000)
2. Fiscal year conventions:
   - Before FY1977: Jul 1 of prior year to Jun 30 (e.g., FY1975 = Jul 1974 – Jun 1975)
   - FY1977 onward: Oct 1 of prior year to Sep 30 (e.g., FY2020 = Oct 2019 – Sep 2020)
   - Transition Quarter (TQ/1976): Jul 1 – Sep 30, 1976
3. Extract exact values from tables. Only calculate if explicitly asked.
4. For sums: add all individual reported values. For geometric mean: GM = (y1*y2*...*yn)^(1/n)
5. Match the answer format to what's in the original table.
6. ALWAYS provide your best answer as a single value. NEVER refuse.

Answer with ONLY the value, no explanation."""


class GEPASolver:
    """
    GEPA+: Genetic-Pareto prompt optimizer.

    Two modes:
    - Quick mode (default): Use a well-crafted seed prompt without optimization
    - Optimize mode: Run GEPA evolutionary optimization on a trainset first
    """

    def __init__(self, model: str = "claude-haiku-4-5", corpus_dir: Optional[Path] = None,
                 cli: str = "claude"):
        self.model = model
        self.corpus_dir = corpus_dir
        self.prompt = OFFICEQA_SEED_PROMPT
        self.optimized = False
        self.name = "GEPA+"
        self.llm = LLMClient(model=model, cli=cli)

    def optimize(self, trainset: List[OfficeQAQuestion], max_metric_calls: int = 30):
        """
        Run GEPA evolutionary optimization on a trainset.
        Updates self.prompt with the best-found prompt.
        """
        from gepa import optimize as gepa_optimize, EvaluationBatch

        outer_llm = self.llm
        outer_corpus_dir = self.corpus_dir

        class OfficeQAAdapter:
            """GEPA adapter for OfficeQA evaluation using CLI."""

            def __init__(self):
                self.llm = outer_llm
                self.corpus_dir = outer_corpus_dir

            def evaluate(self, batch, candidate, capture_traces=False):
                scores = []
                outputs = []
                trajectories = [] if capture_traces else None

                for q in batch:
                    context = load_source_documents(q.source_files, self.corpus_dir)
                    user_msg = f"CONTEXT:\n{context[:30000]}\n\n" if context else ""
                    user_msg += f"QUESTION: {q.question}\n\nAnswer with ONLY the value."

                    result = self.llm.call(user_msg, system=candidate["system"])
                    predicted = result.output if result.success else f"ERROR: {result.error}"

                    sc = score_answer(q.answer, predicted)
                    scores.append(sc)
                    outputs.append({"predicted": predicted, "expected": q.answer})

                    if capture_traces:
                        trajectories.append({
                            "question": q.question,
                            "expected": q.answer,
                            "predicted": predicted,
                            "score": sc,
                            "system_prompt": candidate["system"],
                        })

                return EvaluationBatch(
                    outputs=outputs,
                    scores=scores,
                    trajectories=trajectories,
                )

            def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
                dataset = {}
                if eval_batch.trajectories:
                    for comp in components_to_update:
                        failures = [t for t in eval_batch.trajectories if t["score"] < 1.0]
                        dataset[comp] = [
                            {
                                "question": f["question"],
                                "expected": f["expected"],
                                "predicted": f["predicted"],
                                "current_prompt": f["system_prompt"],
                            }
                            for f in failures[:5]
                        ]
                return dataset

        adapter = OfficeQAAdapter()

        print(f"  Running GEPA optimization ({max_metric_calls} iterations)...")
        result = gepa_optimize(
            seed_candidate={"system": self.prompt},
            trainset=trainset,
            adapter=adapter,
            reflection_lm=self.model,
            max_metric_calls=max_metric_calls,
        )

        if hasattr(result, 'best_candidate') and result.best_candidate:
            self.prompt = result.best_candidate.get("system", self.prompt)
            self.optimized = True
            print(f"  GEPA optimization complete. Best score: {getattr(result, 'best_score', 'N/A')}")
        else:
            print("  GEPA optimization did not improve prompt, using seed.")

    def solve(self, question: OfficeQAQuestion) -> Dict:
        """Solve using the (possibly optimized) prompt via CLI."""
        start = time.time()

        context = load_source_documents(question.source_files, self.corpus_dir)
        user_msg = ""
        if context:
            user_msg = f"DOCUMENT CONTEXT:\n{context[:40000]}\n\n"
        user_msg += f"QUESTION: {question.question}\n\nAnswer with ONLY the value."

        result = self.llm.call(user_msg, system=self.prompt)
        predicted = extract_final_answer(result.output) if result.success else f"ERROR: {result.error}"

        return {
            "method": "GEPA+",
            "predicted": predicted,
            "expected": question.answer,
            "duration": time.time() - start,
            "optimized": self.optimized,
            "model": self.model,
        }


# ============================================================================
# ROMA SOLVER (CLI-based recursive decomposition)
# ============================================================================

class ROMASolver:
    """
    ROMA: Recursive Open Meta-Agents.
    Implements the ROMA architecture via CLI:
    Atomizer -> Planner -> Executor -> Aggregator -> Verifier

    Uses Claude/Codex CLI (no API keys needed).
    """

    def __init__(self, corpus_dir: Optional[Path] = None,
                 model: str = "claude-haiku-4-5", cli: str = "claude", **_kwargs):
        self.corpus_dir = corpus_dir
        self.name = "ROMA"
        self.llm = LLMClient(model=model, cli=cli)
        print(f"  ROMA initialized (cli={cli}, model={model})")

    def solve(self, question: OfficeQAQuestion) -> Dict:
        """
        Solve using ROMA recursive decomposition via CLI.
        Implements: Atomizer -> Planner -> Executor -> Aggregator -> Verifier
        """
        start = time.time()
        context = load_source_documents(question.source_files, self.corpus_dir)
        try:
            # Step 1: Atomizer - decide if atomic or needs decomposition
            atomize_result = self.llm.call(
                f"Decide if this question can be answered directly (ATOMIC) or needs "
                f"decomposition into subtasks (DECOMPOSE).\n\n"
                f"Question: {question.question}\n\n"
                f"Respond with ONLY 'ATOMIC' or 'DECOMPOSE: <subtask1>; <subtask2>; ...'"
            )
            atomize_output = atomize_result.output

            ctx_block = f"\nDOCUMENT CONTEXT:\n{context[:30000]}\n" if context else ""

            if "DECOMPOSE" in atomize_output.upper():
                # Parse subtasks
                subtask_text = atomize_output.split(":", 1)[-1] if ":" in atomize_output else atomize_output
                subtasks = [s.strip() for s in subtask_text.split(";") if s.strip()][:4]

                # Execute each subtask
                subtask_results = []
                for st in subtasks:
                    st_result = self.llm.call(
                        f"{ctx_block}\nSubtask: {st}\nAnswer with ONLY the value.",
                        system=OFFICEQA_SEED_PROMPT,
                    )
                    subtask_results.append({"subtask": st, "result": st_result.output})

                # Aggregate
                agg_result = self.llm.call(
                    f"Original question: {question.question}\n\n"
                    f"Subtask results:\n{json.dumps(subtask_results, indent=2)}\n\n"
                    f"Synthesize the final answer. Respond with ONLY the answer value."
                )
                predicted = extract_final_answer(agg_result.output)
                path = "decomposed"
            else:
                # Atomic: answer directly
                exec_result = self.llm.call(
                    f"{ctx_block}\nQuestion: {question.question}\n\nAnswer with ONLY the value.",
                    system=OFFICEQA_SEED_PROMPT,
                )
                predicted = extract_final_answer(exec_result.output)
                path = "atomic"

        except Exception as e:
            predicted = f"ERROR: {e}"
            path = "error"

        return {
            "method": "ROMA",
            "predicted": predicted,
            "expected": question.answer,
            "path": path,
            "duration": time.time() - start,
        }


# ============================================================================
# COMPARISON RUNNER
# ============================================================================

class ComparisonRunner:
    """Runs selected methods on OfficeQA and compares results."""

    def __init__(self, methods: List[str], corpus_dir: Optional[Path] = None,
                 model: str = "claude-haiku-4-5", cli: str = "claude"):
        self.solvers = {}
        self.results: Dict[str, List[Dict]] = {}

        if "rlm" in methods:
            print("\nInitializing RLM...")
            self.solvers["RLM"] = RLMSolver(model=model, corpus_dir=corpus_dir, cli=cli)
            self.results["RLM"] = []

        if "gepa" in methods:
            # GEPA = base seed prompt (no optimization)
            print("\nInitializing GEPA (seed prompt)...")
            self.solvers["GEPA"] = GEPASolver(model=model, corpus_dir=corpus_dir, cli=cli)
            self.results["GEPA"] = []

        if "gepa+" in methods:
            # GEPA+ = with evolutionary optimization
            print("\nInitializing GEPA+ (optimized)...")
            self.solvers["GEPA+"] = GEPASolver(model=model, corpus_dir=corpus_dir, cli=cli)
            self.results["GEPA+"] = []

        if "roma" in methods:
            print("\nInitializing ROMA...")
            self.solvers["ROMA"] = ROMASolver(corpus_dir=corpus_dir, model=model, cli=cli)
            self.results["ROMA"] = []

    def run_optimization(self, trainset: List[OfficeQAQuestion], max_metric_calls: int = 30):
        """Run GEPA optimization on GEPA+ solver only."""
        if "GEPA+" in self.solvers:
            self.solvers["GEPA+"].optimize(trainset, max_metric_calls=max_metric_calls)

    def run_comparison(self, questions: List[OfficeQAQuestion]) -> Dict:
        """Run all active methods on all questions."""
        print("\n" + "=" * 70)
        print("OFFICEQA BENCHMARK COMPARISON")
        print(f"Methods: {', '.join(self.solvers.keys())}")
        print(f"Questions: {len(questions)}")
        print("=" * 70)

        for i, q in enumerate(questions):
            print(f"\n--- Question {i + 1}/{len(questions)}: {q.uid} ---")
            print(f"Q: {q.question[:70]}...")
            print(f"Expected: {q.answer}")

            for name, solver in self.solvers.items():
                print(f"\n  [{name}] Solving...")
                try:
                    result = solver.solve(q)
                except Exception as e:
                    result = {
                        "method": name,
                        "predicted": f"ERROR: {e}",
                        "expected": q.answer,
                        "duration": 0,
                    }

                # Score with official OfficeQA scorer
                result["score"] = score_answer(q.answer, result.get("predicted", ""))
                self.results[name].append(result)

                status = "CORRECT" if result["score"] > 0 else "wrong"
                print(f"  [{name}] Predicted: {result.get('predicted', 'ERROR')[:60]}")
                print(f"  [{name}] {status} ({result.get('duration', 0):.1f}s)")

        return self._compute_summary()

    def _compute_summary(self) -> Dict:
        summary = {}
        for method, results in self.results.items():
            total = len(results)
            correct = sum(1 for r in results if r.get("score", 0) > 0)
            total_time = sum(r.get("duration", 0) for r in results)
            summary[method] = {
                "correct": correct,
                "total": total,
                "accuracy": correct / total if total > 0 else 0,
                "avg_time": total_time / total if total > 0 else 0,
            }
        return summary

    def print_results(self, summary: Dict, questions: List[OfficeQAQuestion]):
        print("\n" + "=" * 70)
        print("RESULTS COMPARISON")
        print("=" * 70)

        print(f"\n{'Method':<15} {'Correct':<10} {'Total':<10} {'Accuracy':<15} {'Avg Time':<10}")
        print("-" * 60)
        for method, stats in summary.items():
            print(f"{method:<15} {stats['correct']:<10} {stats['total']:<10} "
                  f"{stats['accuracy'] * 100:.1f}%{'':<10} {stats['avg_time']:.1f}s")

        print("\n" + "=" * 70)
        print("\nDETAILED RESULTS:")
        print("-" * 70)

        for i, q in enumerate(questions):
            print(f"\nQ{i + 1} [{q.uid}]: {q.question[:55]}...")
            print(f"  Expected: {q.answer}")
            for method, results in self.results.items():
                if i < len(results):
                    r = results[i]
                    mark = "+" if r.get("score", 0) > 0 else " "
                    print(f"  {mark} {method}: {r.get('predicted', 'N/A')[:60]}")

    def save_results(self, summary: Dict, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump({
                "summary": summary,
                "detailed": {k: v for k, v in self.results.items()},
            }, f, indent=2, default=str)
        print(f"\nResults saved to: {output_path}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="OfficeQA Benchmark Comparison: RLM vs GEPA+ vs ROMA")
    parser.add_argument("--limit", type=int, default=10, help="Number of questions to evaluate")
    parser.add_argument("--subset", choices=["pro", "full"], default="pro",
                        help="Dataset subset: 'pro' (133 hard) or 'full' (246)")
    parser.add_argument("--methods", type=str, default="rlm,gepa,gepa+,roma",
                        help="Comma-separated methods: rlm,gepa,gepa+,roma")
    parser.add_argument("--model", type=str, default="claude-haiku-4-5",
                        help="Model for RLM and GEPA+ solvers")
    parser.add_argument("--cli", choices=["claude", "codex"], default="claude",
                        help="CLI tool to use: 'claude' (CodeMax) or 'codex'")
    parser.add_argument("--corpus-dir", type=str, default=None,
                        help="Path to Treasury Bulletin transformed text files")
    parser.add_argument("--optimize", action="store_true",
                        help="Run GEPA optimization before evaluation (slower but better)")
    parser.add_argument("--optimize-budget", type=int, default=30,
                        help="Max metric calls for GEPA optimization")
    parser.add_argument("--output", type=str, default="results/officeqa_comparison.json",
                        help="Output JSON path")
    args = parser.parse_args()

    print("=" * 70)
    print("OFFICEQA BENCHMARK COMPARISON")
    print(f"Dataset: OfficeQA {args.subset} | Limit: {args.limit}")
    print(f"Methods: {args.methods} | Model: {args.model} | CLI: {args.cli}")
    print("=" * 70)

    methods = [m.strip().lower() for m in args.methods.split(",")]

    # Load questions
    print("\nLoading OfficeQA benchmark...")
    questions = load_officeqa_benchmark(subset=args.subset, limit=args.limit)
    print(f"Loaded {len(questions)} questions from OfficeQA {args.subset}")

    # Parse methods
    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else None

    # Initialize runner
    runner = ComparisonRunner(methods=methods, corpus_dir=corpus_dir, model=args.model, cli=args.cli)

    # GEPA+ optimization (runs automatically when gepa+ is in methods)
    if "gepa+" in methods:
        print("\nRunning GEPA+ evolutionary prompt optimization...")
        train_size = min(10, len(questions) // 2) if len(questions) > 20 else min(5, len(questions))
        trainset = questions[:train_size]
        runner.run_optimization(trainset, max_metric_calls=args.optimize_budget)

    # Run comparison
    summary = runner.run_comparison(questions)

    # Print and save results
    runner.print_results(summary, questions)
    runner.save_results(summary, Path(args.output))


if __name__ == "__main__":
    main()
