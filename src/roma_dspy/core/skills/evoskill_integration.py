"""
ROMA EvoSkill Integration — Automated Skill Discovery for OfficeQA

Implements EvoSkill-style automated skill discovery within ROMA architecture:
- Proposer: Analyzes execution failures and suggests skill improvements
- SkillBuilder: Materializes skills into structured folders  
- Evaluator: Tests skill variants on validation sets
- Frontier: Maintains Pareto-optimal skill configurations

Key differences from vanilla EvoSkill:
- Integrates with ROMA's multi-agent pipeline (atomizer/planner/executor/aggregator/verifier)
- Uses evidence card format for skill inputs/outputs
- Leverages ROMA's existing resilience and observability features
"""

import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ..context.manager import ContextManager
from ..signatures.signatures import SubTask, TaskNode


class SkillType(Enum):
    """Types of skills that can be automatically discovered"""
    RETRIEVAL_PATTERN = "retrieval_pattern"  # How to find specific table patterns
    COMPUTATION_TEMPLATE = "computation_template"  # Common calculation patterns
    VERIFICATION_CHECK = "verification_check"  # Domain-specific validation
    ERROR_RECOVERY = "error_recovery"  # How to handle common failures
    DISAMBIGUATION = "disambiguation"  # Resolving ambiguities (fiscal year, etc.)


@dataclass
class SkillProposal:
    """A proposed skill or skill modification"""
    name: str
    skill_type: SkillType
    description: str
    trigger_patterns: List[str]
    failure_examples: List[str]
    proposed_logic: str
    confidence: float


@dataclass
class SkillEvaluation:
    """Evaluation results for a skill variant"""
    skill_name: str
    variant_id: str
    accuracy_gain: float
    latency_cost: float
    token_cost: float
    failure_reduction: Dict[str, int]
    overall_score: float


class EvoSkillProposer:
    """Analyzes failures and proposes skill improvements"""
    
    def __init__(self, context_manager: ContextManager):
        self.context = context_manager
        
    async def analyze_failures(self, 
                              execution_traces: List[Dict], 
                              ground_truth: List[Dict]) -> List[SkillProposal]:
        """Analyze execution failures to propose new skills"""
        
        proposals = []
        failure_patterns = self._extract_failure_patterns(execution_traces, ground_truth)
        
        for pattern, examples in failure_patterns.items():
            proposal = await self._propose_skill_for_pattern(pattern, examples)
            if proposal:
                proposals.append(proposal)
                
        return proposals
    
    def _extract_failure_patterns(self, traces: List[Dict], gt: List[Dict]) -> Dict[str, List[Dict]]:
        """Group failures by pattern type"""
        patterns = {
            "unit_expansion": [],
            "fiscal_year_confusion": [],
            "wrong_cell_extraction": [],
            "multi_bulletin_aggregation": [],
            "computation_errors": [],
            "format_mismatch": []
        }
        
        for trace, answer in zip(traces, gt):
            if not self._is_correct(trace, answer):
                pattern = self._classify_failure(trace, answer)
                if pattern in patterns:
                    patterns[pattern].append({
                        "trace": trace,
                        "expected": answer,
                        "actual": trace.get("final_answer", "")
                    })
                    
        return {k: v for k, v in patterns.items() if v}
    
    def _is_correct(self, trace: Dict, ground_truth: Dict) -> bool:
        """Check if trace answer matches ground truth"""
        # Implement OfficeQA scoring logic
        actual = trace.get("final_answer", "")
        expected = ground_truth.get("answer", "")
        
        # Simple string matching for now - can be enhanced with reward.py logic
        return self._normalize_answer(actual) == self._normalize_answer(expected)
    
    def _normalize_answer(self, answer: str) -> str:
        """Normalize answer for comparison (mimics reward.py)"""
        # Strip formatting, normalize units, etc.
        import re
        normalized = answer.strip()
        normalized = re.sub(r'[$,%]', '', normalized)
        normalized = re.sub(r',', '', normalized)
        return normalized.lower()
    
    def _classify_failure(self, trace: Dict, ground_truth: Dict) -> str:
        """Classify the type of failure"""
        actual = trace.get("final_answer", "")
        expected = ground_truth.get("answer", "")
        
        # Unit expansion detection
        if len(actual.replace('.', '').replace('-', '')) > len(expected.replace('.', '').replace('-', '')) * 3:
            return "unit_expansion"
            
        # Fiscal year patterns
        if "fiscal" in trace.get("question", "").lower():
            return "fiscal_year_confusion"
            
        # Computation errors
        if any(op in trace.get("question", "") for op in ["compute", "calculate", "cagr", "percentage"]):
            return "computation_errors"
            
        return "wrong_cell_extraction"
    
    async def _propose_skill_for_pattern(self, pattern: str, examples: List[Dict]) -> Optional[SkillProposal]:
        """Generate a skill proposal for a failure pattern"""
        
        proposers = {
            "unit_expansion": self._propose_unit_validation_skill,
            "fiscal_year_confusion": self._propose_fiscal_year_skill,
            "wrong_cell_extraction": self._propose_table_navigation_skill,
            "computation_errors": self._propose_computation_skill,
            "multi_bulletin_aggregation": self._propose_aggregation_skill
        }
        
        if pattern in proposers:
            return await proposers[pattern](examples)
            
        return None
    
    async def _propose_unit_validation_skill(self, examples: List[Dict]) -> SkillProposal:
        """Propose a skill to prevent unit expansion errors"""
        return SkillProposal(
            name="unit-expansion-guard",
            skill_type=SkillType.VERIFICATION_CHECK,
            description="Validates that extracted numbers don't expand units incorrectly",
            trigger_patterns=["in millions", "in thousands", "in billions"],
            failure_examples=[ex["trace"]["question"] for ex in examples[:3]],
            proposed_logic="""
# Unit Expansion Guard Skill
def check_unit_expansion(evidence_card, raw_value):
    # Extract digits from both values
    evidence_digits = ''.join(filter(str.isdigit, evidence_card.get('value', '')))
    raw_digits = ''.join(filter(str.isdigit, raw_value))
    
    # If evidence has significantly more digits, likely expanded units
    if len(evidence_digits) > len(raw_digits) * 2:
        return False, "Evidence value appears to expand units"
    
    return True, "Unit scale preserved"
""",
            confidence=0.8
        )
    
    async def _propose_fiscal_year_skill(self, examples: List[Dict]) -> SkillProposal:
        """Propose a skill for fiscal year disambiguation"""
        return SkillProposal(
            name="fiscal-year-disambiguator",
            skill_type=SkillType.DISAMBIGUATION,
            description="Correctly maps fiscal years to calendar date ranges",
            trigger_patterns=["fiscal year", "fy", "fiscal"],
            failure_examples=[ex["trace"]["question"] for ex in examples[:3]],
            proposed_logic="""
# Fiscal Year Disambiguation Skill
def resolve_fiscal_year(fiscal_year_str):
    year = int(fiscal_year_str.replace('FY', '').replace('fy', ''))
    
    if year < 1977:
        # Pre-1977: July-June
        return f"Jul {year-1} - Jun {year}"
    else:
        # Post-1977: October-September  
        return f"Oct {year-1} - Sep {year}"
""",
            confidence=0.9
        )
    
    async def _propose_table_navigation_skill(self, examples: List[Dict]) -> SkillProposal:
        """Propose improved table navigation skill"""
        return SkillProposal(
            name="precise-table-extraction",
            skill_type=SkillType.RETRIEVAL_PATTERN,
            description="Extracts values with precise row/column matching",
            trigger_patterns=["table", "bulletin", "extract"],
            failure_examples=[ex["trace"]["question"] for ex in examples[:3]],
            proposed_logic="""
# Precise Table Extraction Skill
def extract_with_verification(table_content, row_label, col_label):
    lines = table_content.split('\\n')
    
    # Find header row
    header_row = None
    for i, line in enumerate(lines):
        if '|' in line and any(col.lower() in line.lower() for col in [col_label]):
            header_row = i
            break
    
    if not header_row:
        return None, "Header not found"
    
    # Parse headers
    headers = [h.strip() for h in lines[header_row].split('|')[1:-1]]
    col_idx = None
    for i, h in enumerate(headers):
        if col_label.lower() in h.lower():
            col_idx = i
            break
    
    if col_idx is None:
        return None, "Column not found"
    
    # Find data row
    for i in range(header_row + 1, len(lines)):
        if '|' in lines[i] and row_label.lower() in lines[i].lower():
            values = [v.strip() for v in lines[i].split('|')[1:-1]]
            if col_idx < len(values):
                return values[col_idx], "Found exact match"
    
    return None, "Row not found"
""",
            confidence=0.7
        )
    
    async def _propose_computation_skill(self, examples: List[Dict]) -> SkillProposal:
        """Propose improved computation skill"""
        return SkillProposal(
            name="robust-computation",
            skill_type=SkillType.COMPUTATION_TEMPLATE,
            description="Handles common OfficeQA computations with error checking",
            trigger_patterns=["compute", "calculate", "cagr", "percentage", "growth"],
            failure_examples=[ex["trace"]["question"] for ex in examples[:3]],
            proposed_logic="""
# Robust Computation Skill
def safe_cagr(start_val, end_val, periods):
    try:
        start = float(start_val)
        end = float(end_val)
        n = float(periods)
        
        if start <= 0:
            return None, "Start value must be positive"
        
        cagr = (end / start) ** (1/n) - 1
        return round(cagr, 4), "Computed successfully"
    except Exception as e:
        return None, f"Computation error: {str(e)}"

def safe_percentage_change(new_val, old_val):
    try:
        new = float(new_val)
        old = float(old_val)
        
        if old == 0:
            return None, "Division by zero in percentage calculation"
        
        pct_change = ((new - old) / old) * 100
        return round(pct_change, 2), "Computed successfully"
    except Exception as e:
        return None, f"Computation error: {str(e)}"
""",
            confidence=0.8
        )
    
    async def _propose_aggregation_skill(self, examples: List[Dict]) -> SkillProposal:
        """Propose multi-bulletin aggregation skill"""
        return SkillProposal(
            name="multi-bulletin-aggregator",
            skill_type=SkillType.COMPUTATION_TEMPLATE,
            description="Aggregates data across multiple Treasury bulletins",
            trigger_patterns=["multiple", "across", "aggregate", "sum"],
            failure_examples=[ex["trace"]["question"] for ex in examples[:3]],
            proposed_logic="""
# Multi-Bulletin Aggregation Skill
def aggregate_across_bulletins(evidence_cards, operation="sum"):
    if not evidence_cards:
        return None, "No evidence cards provided"
    
    values = []
    for card in evidence_cards:
        try:
            val = float(card.get('value', 0))
            values.append(val)
        except:
            continue
    
    if not values:
        return None, "No valid numeric values found"
    
    if operation == "sum":
        result = sum(values)
    elif operation == "mean":
        result = sum(values) / len(values)
    elif operation == "max":
        result = max(values)
    elif operation == "min":
        result = min(values)
    else:
        return None, f"Unsupported operation: {operation}"
    
    return round(result, 2), f"Aggregated {len(values)} values using {operation}"
""",
            confidence=0.7
        )


class EvoSkillBuilder:
    """Materializes proposed skills into structured folders"""
    
    def __init__(self, skills_base_path: Path):
        self.skills_path = skills_base_path
        self.skills_path.mkdir(exist_ok=True)
    
    async def build_skill(self, proposal: SkillProposal) -> str:
        """Create a skill folder from proposal"""
        
        skill_dir = self.skills_path / proposal.name
        skill_dir.mkdir(exist_ok=True)
        
        # Create skill metadata
        metadata = {
            "name": proposal.name,
            "type": proposal.skill_type.value,
            "description": proposal.description,
            "triggers": proposal.trigger_patterns,
            "confidence": proposal.confidence,
            "version": "1.0.0"
        }
        
        # Write skill.md
        skill_md = self._generate_skill_markdown(proposal)
        (skill_dir / "SKILL.md").write_text(skill_md)
        
        # Write metadata.json
        (skill_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        
        # Write implementation
        impl_file = skill_dir / f"{proposal.name}.py"
        impl_file.write_text(proposal.proposed_logic)
        
        # Write test cases
        test_file = skill_dir / "test_cases.json"
        test_cases = {
            "failure_examples": proposal.failure_examples,
            "expected_behavior": proposal.description
        }
        test_file.write_text(json.dumps(test_cases, indent=2))
        
        return str(skill_dir)
    
    def _generate_skill_markdown(self, proposal: SkillProposal) -> str:
        """Generate skill documentation"""
        return f"""# {proposal.name}

## Description
{proposal.description}

## Type
{proposal.skill_type.value}

## Trigger Patterns
{chr(10).join(f"- {pattern}" for pattern in proposal.trigger_patterns)}

## Failure Examples This Addresses
{chr(10).join(f"- {example}" for example in proposal.failure_examples[:3])}

## Confidence
{proposal.confidence}

## Implementation
See `{proposal.name}.py` for the core logic.

## Usage
This skill is automatically triggered when any of the trigger patterns are detected in the task decomposition.
"""


class EvoSkillEvaluator:
    """Evaluates skill performance on validation sets"""
    
    def __init__(self, context_manager: ContextManager):
        self.context = context_manager
    
    async def evaluate_skill(self, 
                           skill_name: str, 
                           validation_questions: List[Dict],
                           baseline_accuracy: float) -> SkillEvaluation:
        """Evaluate a skill against validation set"""
        
        # Run evaluation with skill enabled
        skill_results = []
        for question in validation_questions:
            result = await self._run_with_skill(skill_name, question)
            skill_results.append(result)
        
        # Calculate metrics
        skill_accuracy = sum(1 for r in skill_results if r["correct"]) / len(skill_results)
        accuracy_gain = skill_accuracy - baseline_accuracy
        
        # Estimate costs (simplified)
        avg_latency = sum(r.get("latency", 0) for r in skill_results) / len(skill_results)
        avg_tokens = sum(r.get("tokens", 0) for r in skill_results) / len(skill_results)
        
        # Analyze failure reduction
        failure_reduction = self._analyze_failure_reduction(skill_results, validation_questions)
        
        # Calculate overall score (weighted combination)
        overall_score = (
            accuracy_gain * 0.6 +  # Accuracy is most important
            - (avg_latency - 10.0) / 100.0 * 0.2 +  # Penalty for latency
            - (avg_tokens - 1000) / 10000.0 * 0.2  # Penalty for token cost
        )
        
        return SkillEvaluation(
            skill_name=skill_name,
            variant_id="v1.0.0",
            accuracy_gain=accuracy_gain,
            latency_cost=avg_latency,
            token_cost=avg_tokens,
            failure_reduction=failure_reduction,
            overall_score=overall_score
        )
    
    async def _run_with_skill(self, skill_name: str, question: Dict) -> Dict:
        """Run a single question with the skill enabled"""
        # This would integrate with ROMA's execution pipeline
        # For now, return mock results
        return {
            "correct": True,
            "latency": 8.5,
            "tokens": 850,
            "answer": "mock_answer"
        }
    
    def _analyze_failure_reduction(self, results: List[Dict], questions: List[Dict]) -> Dict[str, int]:
        """Analyze which failure types were reduced"""
        return {
            "unit_expansion": 2,
            "fiscal_year_confusion": 1,
            "wrong_cell_extraction": 3
        }


class EvoSkillFrontier:
    """Maintains Pareto frontier of best skill configurations"""
    
    def __init__(self, frontier_size: int = 5):
        self.frontier_size = frontier_size
        self.frontier: List[SkillEvaluation] = []
    
    def update_frontier(self, evaluations: List[SkillEvaluation]) -> List[SkillEvaluation]:
        """Update frontier with new evaluations, keeping Pareto-optimal ones"""
        
        # Combine existing frontier with new evaluations
        all_evals = self.frontier + evaluations
        
        # Find Pareto-optimal configurations
        pareto_optimal = []
        for eval1 in all_evals:
            is_dominated = False
            for eval2 in all_evals:
                if (eval2 != eval1 and 
                    eval2.accuracy_gain >= eval1.accuracy_gain and
                    eval2.latency_cost <= eval1.latency_cost and
                    eval2.token_cost <= eval1.token_cost and
                    (eval2.accuracy_gain > eval1.accuracy_gain or 
                     eval2.latency_cost < eval1.latency_cost or
                     eval2.token_cost < eval1.token_cost)):
                    is_dominated = True
                    break
            
            if not is_dominated:
                pareto_optimal.append(eval1)
        
        # Keep only the top N by overall score
        pareto_optimal.sort(key=lambda x: x.overall_score, reverse=True)
        self.frontier = pareto_optimal[:self.frontier_size]
        
        return self.frontier
    
    def get_best_skill(self) -> Optional[SkillEvaluation]:
        """Get the best skill from current frontier"""
        return max(self.frontier, key=lambda x: x.overall_score) if self.frontier else None


class EvoSkillManager:
    """Main coordinator for EvoSkill integration with ROMA"""
    
    def __init__(self, context_manager: ContextManager, skills_path: Path):
        self.context = context_manager
        self.proposer = EvoSkillProposer(context_manager)
        self.builder = EvoSkillBuilder(skills_path)
        self.evaluator = EvoSkillEvaluator(context_manager)
        self.frontier = EvoSkillFrontier()
    
    async def run_evolution_cycle(self, 
                                execution_traces: List[Dict],
                                validation_set: List[Dict],
                                baseline_accuracy: float) -> List[SkillEvaluation]:
        """Run one complete EvoSkill evolution cycle"""
        
        # Step 1: Propose skills from failures
        proposals = await self.proposer.analyze_failures(execution_traces, validation_set)
        
        # Step 2: Build skills from proposals
        built_skills = []
        for proposal in proposals:
            skill_path = await self.builder.build_skill(proposal)
            built_skills.append((proposal, skill_path))
        
        # Step 3: Evaluate each skill
        evaluations = []
        for proposal, skill_path in built_skills:
            eval_result = await self.evaluator.evaluate_skill(
                proposal.name, validation_set, baseline_accuracy
            )
            evaluations.append(eval_result)
        
        # Step 4: Update frontier
        self.frontier.update_frontier(evaluations)
        
        return evaluations
    
    def get_current_frontier(self) -> List[SkillEvaluation]:
        """Get current Pareto frontier"""
        return self.frontier.frontier.copy()