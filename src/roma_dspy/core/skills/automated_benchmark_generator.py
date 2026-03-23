"""
Automated Benchmark Generation from Usage Patterns

Addresses the third direction: Creating benchmarks completely automatically
from day-to-day usage patterns to provide feedback signals for evolutionary
algorithms without human intervention.

Key capabilities:
1. Extract test cases from execution traces
2. Generate tool requirements from usage patterns
3. Create prompt specifications from successful/failed runs
4. Build benchmarks from real-world usage, not manual design
"""

import json
import re
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import hashlib


@dataclass
class UsagePattern:
    """Represents a usage pattern extracted from execution traces"""
    pattern_id: str
    pattern_type: str  # "success", "failure", "edge_case"
    question_type: str  # "unit_expansion", "fiscal_year", etc.
    tools_used: List[str]
    prompt_components: Dict[str, str]
    execution_trace: Dict[str, Any]
    outcome: str  # "correct", "incorrect", "partial"
    confidence: float
    timestamp: datetime
    
    # Extracted benchmark components
    test_case: Optional[Dict] = None
    tool_requirements: Optional[Dict] = None
    prompt_spec: Optional[Dict] = None


@dataclass
class GeneratedBenchmark:
    """A benchmark generated from usage patterns"""
    benchmark_id: str
    name: str
    description: str
    test_cases: List[Dict]
    tool_requirements: Dict[str, Any]
    prompt_specifications: Dict[str, str]
    evaluation_criteria: Dict[str, Any]
    source_patterns: List[str]  # Pattern IDs used to generate
    generation_metadata: Dict[str, Any]


class UsagePatternExtractor:
    """Extracts usage patterns from execution traces"""
    
    def __init__(self):
        self.patterns = []
        self.pattern_clusters = defaultdict(list)
    
    async def extract_patterns_from_traces(self, 
                                          execution_traces: List[Dict],
                                          ground_truth: Optional[Dict] = None) -> List[UsagePattern]:
        """Extract usage patterns from execution traces"""
        
        patterns = []
        
        for trace in execution_traces:
            # Extract pattern components
            pattern = await self._extract_single_pattern(trace, ground_truth)
            
            if pattern:
                patterns.append(pattern)
                self.patterns.append(pattern)
                
                # Cluster by pattern type
                cluster_key = f"{pattern.pattern_type}_{pattern.question_type}"
                self.pattern_clusters[cluster_key].append(pattern)
        
        return patterns
    
    async def _extract_single_pattern(self, 
                                     trace: Dict, 
                                     ground_truth: Optional[Dict]) -> Optional[UsagePattern]:
        """Extract a single usage pattern from a trace"""
        
        try:
            # Determine outcome
            predicted = trace.get("final_answer", "")
            expected = ground_truth.get(trace["question_id"], "") if ground_truth else ""
            outcome = self._determine_outcome(predicted, expected)
            
            # Identify pattern type
            pattern_type = self._identify_pattern_type(trace, outcome)
            
            # Identify question type
            question_type = self._identify_question_type(trace)
            
            # Extract tools used
            tools_used = self._extract_tools_used(trace)
            
            # Extract prompt components
            prompt_components = self._extract_prompt_components(trace)
            
            # Generate pattern ID
            pattern_id = self._generate_pattern_id(trace, pattern_type, question_type)
            
            # Calculate confidence
            confidence = self._calculate_pattern_confidence(trace, outcome)
            
            return UsagePattern(
                pattern_id=pattern_id,
                pattern_type=pattern_type,
                question_type=question_type,
                tools_used=tools_used,
                prompt_components=prompt_components,
                execution_trace=trace,
                outcome=outcome,
                confidence=confidence,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            print(f"Error extracting pattern: {e}")
            return None
    
    def _determine_outcome(self, predicted: str, expected: str) -> str:
        """Determine outcome of execution"""
        if not expected:
            return "unknown"
        
        # Normalize for comparison
        pred_norm = self._normalize_answer(predicted)
        exp_norm = self._normalize_answer(expected)
        
        if pred_norm == exp_norm:
            return "correct"
        elif self._partial_match(pred_norm, exp_norm):
            return "partial"
        else:
            return "incorrect"
    
    def _normalize_answer(self, answer: str) -> str:
        """Normalize answer for comparison"""
        normalized = str(answer).strip()
        normalized = re.sub(r'[$,%]', '', normalized)
        normalized = re.sub(r',', '', normalized)
        normalized = normalized.replace('–', '-').replace('—', '-')
        return normalized.lower()
    
    def _partial_match(self, predicted: str, expected: str) -> bool:
        """Check for partial match (e.g., correct magnitude, wrong precision)"""
        # Implementation would check for partial correctness
        return False
    
    def _identify_pattern_type(self, trace: Dict, outcome: str) -> str:
        """Identify the type of usage pattern"""
        if outcome == "correct":
            return "success"
        elif outcome == "incorrect":
            # Check if it's an edge case
            if self._is_edge_case(trace):
                return "edge_case"
            return "failure"
        else:
            return "unknown"
    
    def _is_edge_case(self, trace: Dict) -> bool:
        """Check if trace represents an edge case"""
        # Implementation would detect edge cases
        return False
    
    def _identify_question_type(self, trace: Dict) -> str:
        """Identify the question type from trace"""
        question = trace.get("question", "").lower()
        
        # Pattern matching for OfficeQA question types
        if "fiscal year" in question or "fy" in question:
            return "fiscal_year"
        elif "million" in question or "billion" in question:
            return "unit_expansion"
        elif "bulletin" in question and any(year in question for year in ["1939", "1940", "2025"]):
            return "multi_bulletin"
        elif any(op in question for op in ["calculate", "compute", "percentage", "growth"]):
            return "computation"
        else:
            return "atomic_lookup"
    
    def _extract_tools_used(self, trace: Dict) -> List[str]:
        """Extract tools used during execution"""
        tools = set()
        
        # Check execution steps for tool usage
        for step in trace.get("execution_steps", []):
            tool_name = step.get("tool_used")
            if tool_name:
                tools.add(tool_name)
        
        return list(tools)
    
    def _extract_prompt_components(self, trace: Dict) -> Dict[str, str]:
        """Extract prompt components from trace"""
        components = {}
        
        # Extract system prompt
        if "system_prompt" in trace:
            components["system_prompt"] = trace["system_prompt"]
        
        # Extract few-shot examples used
        if "few_shot_examples" in trace:
            components["few_shot_examples"] = json.dumps(trace["few_shot_examples"])
        
        # Extract task-specific instructions
        if "task_instructions" in trace:
            components["task_instructions"] = trace["task_instructions"]
        
        return components
    
    def _generate_pattern_id(self, trace: Dict, pattern_type: str, question_type: str) -> str:
        """Generate unique pattern ID"""
        content = f"{trace.get('question_id', '')}_{pattern_type}_{question_type}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def _calculate_pattern_confidence(self, trace: Dict, outcome: str) -> float:
        """Calculate confidence score for pattern"""
        # Higher confidence for clear successes/failures
        if outcome == "correct":
            return 0.9
        elif outcome == "incorrect":
            return 0.8
        else:
            return 0.5


class AutomatedBenchmarkGenerator:
    """Generates benchmarks automatically from usage patterns"""
    
    def __init__(self, min_patterns_per_benchmark: int = 10):
        self.extractor = UsagePatternExtractor()
        self.min_patterns = min_patterns_per_benchmark
        self.generated_benchmarks = []
    
    async def generate_benchmark_from_traces(self,
                                           execution_traces: List[Dict],
                                           ground_truth: Optional[Dict] = None,
                                           benchmark_name: str = "auto_generated") -> GeneratedBenchmark:
        """Generate a complete benchmark from execution traces"""
        
        # Extract usage patterns
        patterns = await self.extractor.extract_patterns_from_traces(execution_traces, ground_truth)
        
        if len(patterns) < self.min_patterns:
            raise ValueError(f"Insufficient patterns: {len(patterns)} < {self.min_patterns}")
        
        # Generate test cases from patterns
        test_cases = self._generate_test_cases(patterns)
        
        # Extract tool requirements
        tool_requirements = self._extract_tool_requirements(patterns)
        
        # Generate prompt specifications
        prompt_specifications = self._generate_prompt_specifications(patterns)
        
        # Define evaluation criteria
        evaluation_criteria = self._define_evaluation_criteria(patterns)
        
        # Create benchmark
        benchmark_id = self._generate_benchmark_id(benchmark_name)
        
        benchmark = GeneratedBenchmark(
            benchmark_id=benchmark_id,
            name=benchmark_name,
            description=f"Automatically generated from {len(patterns)} usage patterns",
            test_cases=test_cases,
            tool_requirements=tool_requirements,
            prompt_specifications=prompt_specifications,
            evaluation_criteria=evaluation_criteria,
            source_patterns=[p.pattern_id for p in patterns],
            generation_metadata={
                "total_patterns": len(patterns),
                "success_patterns": len([p for p in patterns if p.pattern_type == "success"]),
                "failure_patterns": len([p for p in patterns if p.pattern_type == "failure"]),
                "edge_cases": len([p for p in patterns if p.pattern_type == "edge_case"]),
                "generation_timestamp": datetime.now().isoformat()
            }
        )
        
        self.generated_benchmarks.append(benchmark)
        
        return benchmark
    
    def _generate_test_cases(self, patterns: List[UsagePattern]) -> List[Dict]:
        """Generate test cases from usage patterns"""
        test_cases = []
        
        for pattern in patterns:
            # Extract question and expected answer from trace
            question = pattern.execution_trace.get("question", "")
            
            # For successful patterns, use the correct answer
            # For failures, we need to determine the correct answer
            if pattern.outcome == "correct":
                expected_answer = pattern.execution_trace.get("final_answer", "")
            else:
                # Try to extract from ground truth or infer
                expected_answer = self._infer_correct_answer(pattern)
            
            test_case = {
                "question_id": pattern.execution_trace.get("question_id", ""),
                "question": question,
                "expected_answer": expected_answer,
                "question_type": pattern.question_type,
                "difficulty": self._estimate_difficulty(pattern),
                "source_pattern": pattern.pattern_id,
                "metadata": {
                    "pattern_type": pattern.pattern_type,
                    "tools_used": pattern.tools_used,
                    "confidence": pattern.confidence
                }
            }
            
            test_cases.append(test_case)
        
        return test_cases
    
    def _infer_correct_answer(self, pattern: UsagePattern) -> str:
        """Infer correct answer from failure patterns"""
        # This would use various heuristics to determine the correct answer
        # For now, return placeholder
        return "REQUIRES_MANUAL_VERIFICATION"
    
    def _estimate_difficulty(self, pattern: UsagePattern) -> str:
        """Estimate difficulty of test case"""
        # Based on pattern characteristics
        if pattern.pattern_type == "edge_case":
            return "hard"
        elif pattern.question_type in ["multi_bulletin", "computation"]:
            return "medium"
        else:
            return "easy"
    
    def _extract_tool_requirements(self, patterns: List[UsagePattern]) -> Dict[str, Any]:
        """Extract tool requirements from patterns"""
        tool_usage = defaultdict(lambda: {"count": 0, "success_rate": 0.0, "contexts": []})
        
        for pattern in patterns:
            for tool in pattern.tools_used:
                tool_usage[tool]["count"] += 1
                
                if pattern.outcome == "correct":
                    tool_usage[tool]["success_rate"] += 1
                
                # Track usage contexts
                context = f"{pattern.question_type}_{pattern.pattern_type}"
                if context not in tool_usage[tool]["contexts"]:
                    tool_usage[tool]["contexts"].append(context)
        
        # Normalize success rates
        for tool in tool_usage:
            count = tool_usage[tool]["count"]
            if count > 0:
                tool_usage[tool]["success_rate"] /= count
        
        # Convert to requirements specification
        requirements = {
            "required_tools": [],
            "optional_tools": [],
            "tool_combinations": [],
            "usage_patterns": dict(tool_usage)
        }
        
        # Classify tools as required vs optional based on usage
        for tool, stats in tool_usage.items():
            if stats["count"] >= len(patterns) * 0.5:  # Used in 50%+ of patterns
                requirements["required_tools"].append(tool)
            else:
                requirements["optional_tools"].append(tool)
        
        # Identify common tool combinations
        tool_combos = defaultdict(int)
        for pattern in patterns:
            combo = tuple(sorted(pattern.tools_used))
            tool_combos[combo] += 1
        
        requirements["tool_combinations"] = [
            {"tools": list(combo), "frequency": count / len(patterns)}
            for combo, count in sorted(tool_combos.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        
        return requirements
    
    def _generate_prompt_specifications(self, patterns: List[UsagePattern]) -> Dict[str, str]:
        """Generate prompt specifications from patterns"""
        
        # Separate successful and failed patterns
        success_patterns = [p for p in patterns if p.pattern_type == "success"]
        failure_patterns = [p for p in patterns if p.pattern_type == "failure"]
        
        # Extract common prompt components from successes
        success_components = defaultdict(list)
        for pattern in success_patterns:
            for key, value in pattern.prompt_components.items():
                success_components[key].append(value)
        
        # Generate specifications
        specifications = {
            "system_prompt_template": self._extract_common_system_prompt(success_components),
            "few_shot_example_patterns": self._extract_few_shot_patterns(success_patterns),
            "task_instruction_patterns": self._extract_task_instructions(success_patterns),
            "failure_avoidance_rules": self._extract_failure_rules(failure_patterns)
        }
        
        return specifications
    
    def _extract_common_system_prompt(self, success_components: Dict[str, List[str]]) -> str:
        """Extract common system prompt from successful patterns"""
        if "system_prompt" in success_components:
            # Find common patterns across system prompts
            prompts = success_components["system_prompt"]
            # Return most common or merged version
            return prompts[0] if prompts else ""
        return ""
    
    def _extract_few_shot_patterns(self, success_patterns: List[UsagePattern]) -> List[Dict]:
        """Extract few-shot example patterns"""
        examples = []
        
        for pattern in success_patterns[:5]:  # Top 5 examples
            example = {
                "question": pattern.execution_trace.get("question", ""),
                "answer": pattern.execution_trace.get("final_answer", ""),
                "type": pattern.question_type
            }
            examples.append(example)
        
        return examples
    
    def _extract_task_instructions(self, success_patterns: List[UsagePattern]) -> List[str]:
        """Extract task instruction patterns"""
        instructions = []
        
        for pattern in success_patterns:
            if "task_instructions" in pattern.prompt_components:
                instructions.append(pattern.prompt_components["task_instructions"])
        
        return list(set(instructions))[:10]  # Unique instructions, max 10
    
    def _extract_failure_rules(self, failure_patterns: List[UsagePattern]) -> List[str]:
        """Extract rules to avoid failures"""
        rules = []
        
        for pattern in failure_patterns:
            # Generate rule based on failure type
            rule = self._generate_failure_rule(pattern)
            if rule:
                rules.append(rule)
        
        return list(set(rules))
    
    def _generate_failure_rule(self, pattern: UsagePattern) -> Optional[str]:
        """Generate a rule to avoid specific failure"""
        if pattern.question_type == "unit_expansion":
            return "Never expand units - preserve base numbers from table headers"
        elif pattern.question_type == "fiscal_year":
            return "Check fiscal year boundaries carefully (pre/post 1977, TQ1976)"
        elif pattern.question_type == "multi_bulletin":
            return "Verify data consistency across multiple bulletins"
        else:
            return None
    
    def _define_evaluation_criteria(self, patterns: List[UsagePattern]) -> Dict[str, Any]:
        """Define evaluation criteria from patterns"""
        
        # Determine scoring metrics based on pattern types
        criteria = {
            "primary_metric": "exact_match_accuracy",
            "secondary_metrics": [],
            "error_type_weights": {},
            "difficulty_weights": {}
        }
        
        # Weight error types based on frequency
        error_type_counts = defaultdict(int)
        for pattern in patterns:
            error_type_counts[pattern.question_type] += 1
        
        total_patterns = len(patterns)
        for error_type, count in error_type_counts.items():
            criteria["error_type_weights"][error_type] = count / total_patterns
        
        # Add secondary metrics
        if any(p.question_type == "computation" for p in patterns):
            criteria["secondary_metrics"].append("numerical_precision")
        
        if any(p.question_type == "multi_bulletin" for p in patterns):
            criteria["secondary_metrics"].append("temporal_consistency")
        
        return criteria
    
    def _generate_benchmark_id(self, name: str) -> str:
        """Generate unique benchmark ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{name}_{timestamp}"


class ContinuousBenchmarkEvolution:
    """Continuously evolves benchmarks based on new usage patterns"""
    
    def __init__(self, 
                 benchmark_generator: AutomatedBenchmarkGenerator,
                 update_frequency: int = 100):  # Update every 100 new traces
        self.generator = benchmark_generator
        self.update_frequency = update_frequency
        self.pending_traces = []
        self.benchmark_versions = []
    
    async def add_execution_trace(self, trace: Dict, ground_truth: Optional[str] = None):
        """Add new execution trace and potentially trigger benchmark update"""
        self.pending_traces.append({
            "trace": trace,
            "ground_truth": ground_truth
        })
        
        # Check if we should update benchmark
        if len(self.pending_traces) >= self.update_frequency:
            await self._update_benchmark()
    
    async def _update_benchmark(self):
        """Update benchmark with new patterns"""
        traces = [item["trace"] for item in self.pending_traces]
        ground_truth = {item["trace"]["question_id"]: item["ground_truth"] 
                       for item in self.pending_traces if item["ground_truth"]}
        
        # Generate new benchmark version
        new_benchmark = await self.generator.generate_benchmark_from_traces(
            traces, 
            ground_truth,
            benchmark_name=f"evolved_v{len(self.benchmark_versions)}"
        )
        
        self.benchmark_versions.append(new_benchmark)
        self.pending_traces = []  # Reset pending traces
        
        print(f"Generated new benchmark version: {new_benchmark.benchmark_id}")
        print(f"Test cases: {len(new_benchmark.test_cases)}")
        print(f"Tool requirements: {len(new_benchmark.tool_requirements['required_tools'])} required")
    
    def get_latest_benchmark(self) -> Optional[GeneratedBenchmark]:
        """Get the latest benchmark version"""
        return self.benchmark_versions[-1] if self.benchmark_versions else None


# Integration with evolutionary algorithms
class EvolutionaryBenchmarkProvider:
    """Provides automatically generated benchmarks to evolutionary algorithms"""
    
    def __init__(self):
        self.generator = AutomatedBenchmarkGenerator()
        self.continuous_evolution = ContinuousBenchmarkEvolution(self.generator)
    
    async def get_benchmark_for_evolution(self, 
                                         execution_traces: List[Dict],
                                         ground_truth: Optional[Dict] = None) -> GeneratedBenchmark:
        """Get benchmark suitable for evolutionary algorithm optimization"""
        
        # Generate benchmark from traces
        benchmark = await self.generator.generate_benchmark_from_traces(
            execution_traces,
            ground_truth,
            benchmark_name="evolution_optimized"
        )
        
        return benchmark
    
    async def continuous_update(self, trace: Dict, ground_truth: Optional[str] = None):
        """Continuously update benchmark with new usage patterns"""
        await self.continuous_evolution.add_execution_trace(trace, ground_truth)
    
    def export_benchmark_for_skydiscover(self, benchmark: GeneratedBenchmark) -> str:
        """Export benchmark in SkyDiscover-compatible format"""
        
        evaluator_code = f'''#!/usr/bin/env python3
"""
Automatically Generated Benchmark Evaluator
Generated from {benchmark.generation_metadata['total_patterns']} usage patterns
"""

import json
import re
from typing import Dict, List

# Test cases from usage patterns
TEST_CASES = {json.dumps(benchmark.test_cases, indent=2)}

# Tool requirements
TOOL_REQUIREMENTS = {json.dumps(benchmark.tool_requirements, indent=2)}

# Prompt specifications
PROMPT_SPECS = {json.dumps(benchmark.prompt_specifications, indent=2)}

def evaluate(solution_code: str, test_data: List[Dict] = None) -> float:
    """Evaluate solution against generated test cases"""
    if test_data is None:
        test_data = TEST_CASES
    
    correct = 0
    total = len(test_data)
    
    # Execute solution code
    exec_globals = {{}}
    exec(solution_code, exec_globals)
    
    for test_case in test_data:
        try:
            # Apply solution to question
            predicted = apply_solution(test_case["question"], exec_globals)
            expected = test_case["expected_answer"]
            
            if normalize_answer(predicted) == normalize_answer(expected):
                correct += 1
        except Exception as e:
            print(f"Error on test case {{test_case['question_id']}}: {{e}}")
    
    return correct / total

def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison"""
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    return normalized.lower()

def apply_solution(question: str, solution_globals: Dict) -> str:
    """Apply solution to question"""
    # This would be customized based on solution structure
    if "solve" in solution_globals:
        return solution_globals["solve"](question)
    else:
        return ""
'''
        
        return evaluator_code


# Main interface
async def create_benchmark_from_usage(execution_traces: List[Dict],
                                     ground_truth: Optional[Dict] = None,
                                     output_path: Optional[str] = None) -> GeneratedBenchmark:
    """Main interface for creating benchmarks from usage patterns"""
    
    provider = EvolutionaryBenchmarkProvider()
    
    # Generate benchmark
    benchmark = await provider.get_benchmark_for_evolution(execution_traces, ground_truth)
    
    # Export if path provided
    if output_path:
        evaluator_code = provider.export_benchmark_for_skydiscover(benchmark)
        
        with open(output_path, 'w') as f:
            f.write(evaluator_code)
        
        print(f"Benchmark exported to: {output_path}")
    
    return benchmark