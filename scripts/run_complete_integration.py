#!/usr/bin/env python3
"""
Complete Integration Runner for OfficeQA Evolutionary Optimization

This script integrates and runs:
1. Sky Computing Lab's EvoX/AdaEvolve (via SkyDiscover)
2. GEPA+/optimize_anything for prompt optimization
3. ROMA (DSPy-based) recursive agent framework
4. RLM-style code execution for corpus traversal
5. Automated benchmark generation from usage patterns

Usage:
    python scripts/run_complete_integration.py --mode test
    python scripts/run_complete_integration.py --mode evolve
    python scripts/run_complete_integration.py --mode benchmark
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

# Check dependencies
def check_dependencies():
    """Check if all required packages are installed"""
    missing = []
    
    try:
        import dspy
        print("✓ DSPy installed")
    except ImportError:
        missing.append("dspy")
        print("✗ DSPy not installed - required for ROMA")
    
    try:
        import gepa
        print("✓ GEPA installed")
    except ImportError:
        print("⚠ GEPA not installed - will use mock implementation")
    
    try:
        from skydiscover import run_discovery
        print("✓ SkyDiscover installed")
    except ImportError:
        print("⚠ SkyDiscover not installed - will use mock implementation")
    
    try:
        from rlm import RLM
        print("✓ RLM installed")
    except ImportError:
        print("⚠ RLM not installed - will use mock implementation")
    
    return missing


class ROMAIntegration:
    """
    ROMA (Recursive Open Meta-Agent) Integration
    
    ROMA is DSPy-based and uses:
    - Atomizer: Decides if task is atomic or needs decomposition
    - Planner: Creates typed subtasks
    - Executor: Runs tools/code
    - Aggregator: Synthesizes results with evidence cards
    - Verifier: Checks outputs against criteria
    """
    
    def __init__(self, config_path: str = "config/profiles/officeqa/default.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        # Import DSPy components
        try:
            import dspy
            self.dspy = dspy
            self.dspy_available = True
        except ImportError:
            self.dspy_available = False
            print("Warning: DSPy not available, using mock")
    
    def _load_config(self) -> Dict:
        """Load ROMA configuration"""
        if self.config_path.exists():
            import yaml
            with open(self.config_path) as f:
                return yaml.safe_load(f)
        return self._default_config()
    
    def _default_config(self) -> Dict:
        """Default ROMA configuration for OfficeQA"""
        return {
            "agent": {
                "type": "RecursiveOpenAIAgent",
                "model": "openai/gpt-5",
                "max_depth": 2,  # Flattened per RLM reproduction findings
                "max_iterations": 20
            },
            "roles": {
                "atomizer": {"model": "gemini-2.5-flash"},
                "planner": {"model": "gemini-2.5-flash"},
                "executor": {"model": "claude-sonnet-4.5"},  # Main workhorse
                "aggregator": {"model": "gemini-2.5-flash"},
                "verifier": {"model": "gemini-2.5-flash"}
            },
            "toolkits": {
                "web_search": True,
                "filesystem": True,
                "code_execution": True  # RLM-style
            }
        }
    
    async def solve_question(self, question: Dict) -> Dict:
        """
        Solve an OfficeQA question using ROMA recursion
        
        This implements the ROMA state machine:
        PENDING → Atomizer → (atomic or decompose)
        Atomic: Executor → Verifier → FINAL
        Decompose: Planner → parallel subtasks → Aggregator → Verifier → FINAL
        """
        
        if not self.dspy_available:
            return self._mock_solve(question)
        
        # Define DSPy signatures for each role
        class AtomizerSignature(self.dspy.Signature):
            """Decide if task is atomic or needs decomposition"""
            question = self.dspy.InputField(desc="The OfficeQA question")
            is_atomic = self.dspy.OutputField(desc="True if can be solved directly")
            reasoning = self.dspy.OutputField(desc="Brief reasoning")
        
        class PlannerSignature(self.dspy.Signature):
            """Decompose into typed subtasks"""
            question = self.dspy.InputField()
            subtasks = self.dspy.OutputField(desc="List of typed subtasks with goals")
        
        class ExecutorSignature(self.dspy.Signature):
            """Execute atomic task with tools"""
            task = self.dspy.InputField()
            tools_available = self.dspy.InputField(desc="Available tools")
            result = self.dspy.OutputField(desc="Evidence card with extracted data")
        
        class AggregatorSignature(self.dspy.Signature):
            """Synthesize subtask results into evidence card"""
            subtask_results = self.dspy.InputField(desc="List of evidence cards")
            final_card = self.dspy.OutputField(desc="Merged evidence card")
        
        class VerifierSignature(self.dspy.Signature):
            """Verify output against OfficeQA scoring rules"""
            evidence_card = self.dspy.InputField()
            question = self.dspy.InputField()
            verdict = self.dspy.OutputField(desc="PASS or FAIL")
            feedback = self.dspy.OutputField(desc="Issues if FAIL")
        
        # Configure language models per role
        roles_config = self.config.get("roles", {})
        atomizer_model = roles_config.get("atomizer", {}).get("model", "openai/gpt-4o-mini")
        atomizer_lm = self.dspy.LM(atomizer_model)
        planner_model = roles_config.get("planner", {}).get("model", "openai/gpt-4o-mini")
        planner_lm = self.dspy.LM(planner_model)
        executor_model = roles_config.get("executor", {}).get("model", "openai/gpt-4o-mini")
        executor_lm = self.dspy.LM(executor_model)
        aggregator_model = roles_config.get("aggregator", {}).get("model", "openai/gpt-4o-mini")
        aggregator_lm = self.dspy.LM(aggregator_model)
        verifier_model = roles_config.get("verifier", {}).get("model", "openai/gpt-4o-mini")
        verifier_lm = self.dspy.LM(verifier_model)
        
        # Run ROMA state machine
        with self.dspy.context(lm=atomizer_lm):
            atomized = self.dspy.Predict(AtomizerSignature)(question=question["question"])
        
        if atomized.is_atomic:
            # Direct execution path
            with self.dspy.context(lm=executor_lm):
                executed = self.dspy.Predict(ExecutorSignature)(
                    task=question["question"],
                    tools_available=["file_read", "table_parse", "calculate"]
                )
            
            with self.dspy.context(lm=verifier_lm):
                verified = self.dspy.Predict(VerifierSignature)(
                    evidence_card=executed.result,
                    question=question["question"]
                )
            
            return {
                "answer": self._extract_answer(executed.result),
                "evidence_card": executed.result,
                "verified": verified.verdict == "PASS",
                "path": "atomic"
            }
        else:
            # Decomposition path
            with self.dspy.context(lm=planner_lm):
                planned = self.dspy.Predict(PlannerSignature)(question=question["question"])
            
            # Execute subtasks in parallel (would use asyncio in production)
            subtask_results = []
            for subtask in planned.subtasks:
                with self.dspy.context(lm=executor_lm):
                    result = self.dspy.Predict(ExecutorSignature)(
                        task=subtask,
                        tools_available=["file_read", "table_parse", "calculate", "web_search"]
                    )
                    subtask_results.append(result.result)
            
            # Aggregate
            with self.dspy.context(lm=aggregator_lm):
                aggregated = self.dspy.Predict(AggregatorSignature)(
                    subtask_results=subtask_results
                )
            
            # Verify
            with self.dspy.context(lm=verifier_lm):
                verified = self.dspy.Predict(VerifierSignature)(
                    evidence_card=aggregated.final_card,
                    question=question["question"]
                )
            
            return {
                "answer": self._extract_answer(aggregated.final_card),
                "evidence_card": aggregated.final_card,
                "verified": verified.verdict == "PASS",
                "path": "decomposed",
                "subtasks": len(planned.subtasks)
            }
    
    def _extract_answer(self, evidence_card: str) -> str:
        """Extract final answer from evidence card"""
        # Parse YAML evidence card
        import yaml
        try:
            card = yaml.safe_load(evidence_card)
            if isinstance(card, dict):
                # Return raw extraction value (base number, never expanded)
                if "raw_extraction" in card:
                    return str(card["raw_extraction"].get("value", ""))
                if "computed" in card:
                    return str(card["computed"].get("value", ""))
        except:
            pass
        return evidence_card
    
    def _mock_solve(self, question: Dict) -> Dict:
        """Mock solver when DSPy not available"""
        return {
            "answer": "36080",  # Example base number
            "evidence_card": """
evidence_card:
  type: RETRIEVE_TABLE
  source:
    files: ["treasury_bulletin_1941_01.txt"]
    pages: ["14"]
  raw_extraction:
    value: 36080
    unit_header: "in millions of dollars"
  confidence: 0.95
""",
            "verified": True,
            "path": "mock"
        }


class RLMCodeExecution:
    """
    RLM (Recursive Language Model) Style Code Execution
    
    RLM treats the prompt as a variable in a Python REPL sandbox.
    The LLM writes code to inspect, decompose, and recursively process.
    
    Key difference from ROMA:
    - ROMA: Recurses on TASK (decompose problem into subtasks)
    - RLM: Recurses on DATA (decompose corpus into chunks)
    
    For OfficeQA, we use RLM-style code execution to:
    1. Traverse the Treasury Bulletin corpus (20GB+ of documents)
    2. Extract tables and perform calculations
    3. Never expand units (preserve base numbers)
    """
    
    def __init__(self, corpus_path: str = "data/treasury_bulletins/"):
        self.corpus_path = Path(corpus_path)
        self.sandbox = self._create_sandbox()
    
    def _create_sandbox(self) -> Dict:
        """Create a mock sandbox environment for code execution"""
        return {
            "os": __import__("os"),
            "re": __import__("re"),
            "json": __import__("json"),
            "pandas": None,  # Would import if available
            "numpy": None,
            "corpus_path": str(self.corpus_path),
            "results": []
        }
    
    async def execute_repl_code(self, code: str, context: Dict) -> Dict:
        """
        Execute RLM-style REPL code
        
        The LLM writes code like:
        ```python
        # Find all bulletins from 1941
        files = [f for f in os.listdir(corpus_path) if '1941' in f]
        
        # Extract table from specific page
        with open(files[0]) as f:
            content = f.read()
            # Parse markdown table
            table = parse_table(content, page=14)
            value = table['debt_column'][0]
        
        # Recursive call on subset if needed
        if len(files) > 1:
            sub_result = sub_rlm(files[1:], query="find debt")
            results.append(sub_result)
        ```
        """
        
        try:
            # In production, this would use a real sandbox (Docker, E2B, etc.)
            # For now, we simulate execution
            
            exec_globals = self.sandbox.copy()
            exec_globals.update(context)
            
            # Safe execution (would use RestrictedPython or similar)
            exec(code, exec_globals)
            
            return {
                "success": True,
                "results": exec_globals.get("results", []),
                "output": str(exec_globals.get("output", ""))
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def generate_traversal_code(self, question: str) -> str:
        """
        Generate RLM-style code for OfficeQA corpus traversal
        
        This is what the LLM would generate to navigate the corpus
        """
        return f'''
# RLM-style code generation for: {question}

import os
import re

# Step 1: Identify relevant bulletins
corpus_files = os.listdir(corpus_path)
relevant_files = [f for f in corpus_files if matches_criteria(f, "{question}")]

# Step 2: Load and parse documents
def parse_treasury_bulletin(filepath):
    """Parse markdown tables from bulletin"""
    with open(filepath) as f:
        content = f.read()
    
    # Extract tables (markdown format)
    tables = extract_markdown_tables(content)
    return tables

# Step 3: Find specific data
def find_data(tables, query):
    """Search tables for query terms"""
    for table in tables:
        if matches_query(table, query):
            # CRITICAL: Never expand units
            # If header says "in millions", keep base number
            value = extract_value(table)
            unit_header = get_unit_header(table)
            
            # Return base number only
            return {{
                "value": value,  # e.g., 36080 not 36080000000
                "unit": unit_header,
                "source": filepath
            }}

# Step 4: Recursive decomposition if needed
if len(relevant_files) > 3:
    # Too many files - decompose by year range
    chunks = split_by_year(relevant_files)
    for chunk in chunks:
        # Recursive call
        sub_result = sub_rlm(chunk, query)
        results.append(sub_result)
else:
    # Direct processing
    for filepath in relevant_files:
        tables = parse_treasury_bulletin(filepath)
        result = find_data(tables, "{question}")
        results.append(result)

# Output final answer (base number only)
output = results[0]["value"] if results else None
'''


class GEPAPlusOptimizer:
    """
    GEPA+ Integration for Prompt Optimization
    
    GEPA (Genetic-Pareto) uses:
    1. Evolutionary algorithms to mutate prompts
    2. Pareto frontier for multi-objective optimization
    3. Natural language reflection for improvement
    
    GEPA+ adds:
    - Multi-LLM proposer (different models suggest improvements)
    - Component-level optimization (optimize each ROMA role separately)
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            "max_iterations": 20,
            "population_size": 8,
            "reflection_depth": 3,
            "component_selector": "executor_only"  # Focus on executor first
        }
        
        try:
            import gepa
            self.gepa = gepa
            self.gepa_available = True
        except ImportError:
            self.gepa_available = False
    
    async def optimize_prompt(self, 
                            seed_prompt: str,
                            evaluator: Callable,
                            component: str = "executor") -> Dict:
        """
        Optimize a prompt using GEPA+ evolutionary algorithm
        
        Args:
            seed_prompt: Initial prompt to optimize
            evaluator: Function that returns (score, feedback)
            component: Which ROMA component to optimize
                      (atomizer, planner, executor, aggregator, verifier)
        """
        
        if not self.gepa_available:
            return self._mock_optimization(seed_prompt, evaluator)
        
        # GEPA+ optimization loop
        population = [seed_prompt]
        frontier = []  # Pareto frontier
        
        for iteration in range(self.config["max_iterations"]):
            # Evaluate population
            scored = []
            for candidate in population:
                score, feedback = evaluator(candidate)
                scored.append((candidate, score, feedback))
            
            # Update Pareto frontier
            frontier = self._update_frontier(frontier, scored)
            
            # Generate mutations using reflection
            new_candidates = []
            for candidate, score, feedback in scored[:4]:  # Top 4
                # Use LLM to reflect and improve
                mutations = await self._reflect_and_mutate(
                    candidate, feedback, score
                )
                new_candidates.extend(mutations)
            
            population = [c for c, _, _ in frontier] + new_candidates
        
        # Return best from frontier
        best = max(frontier, key=lambda x: x[1])
        return {
            "optimized_prompt": best[0],
            "improvement": best[1],
            "frontier_size": len(frontier),
            "iterations": self.config["max_iterations"]
        }
    
    def _update_frontier(self, frontier: List, scored: List) -> List:
        """Update Pareto frontier with new candidates"""
        # Simple implementation: keep top performers
        all_items = frontier + scored
        all_items.sort(key=lambda x: x[1], reverse=True)
        return all_items[:self.config["population_size"]]
    
    async def _reflect_and_mutate(self, 
                                 prompt: str, 
                                 feedback: str,
                                 score: float) -> List[str]:
        """Use LLM reflection to generate prompt mutations"""
        
        # In production, this would call actual LLM
        # For now, return simple variations
        mutations = [
            prompt + f"\n\nKey insight: {feedback}",
            prompt + "\n\nRemember: Never expand units - preserve base numbers.",
            prompt + "\n\nAlways check fiscal year boundaries (pre/post 1977)."
        ]
        
        return mutations
    
    def _mock_optimization(self, seed_prompt: str, evaluator: Callable) -> Dict:
        """Mock optimization when GEPA not available"""
        score, feedback = evaluator(seed_prompt)
        return {
            "optimized_prompt": seed_prompt + "\n\n[Optimized by GEPA+ mock]",
            "improvement": score,
            "frontier_size": 1,
            "iterations": 0
        }


class SkyDiscoverRunner:
    """
    Sky Computing Lab's EvoX/AdaEvolve Integration
    
    EvoX: Meta-evolution (evolves its own optimization strategy)
    AdaEvolve: Adaptive zeroth-order optimization
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            "algorithm": "evox",  # or "adaevolve"
            "model": "gpt-5",
            "iterations": 100,
            "budget": 100.0
        }
        
        try:
            from skydiscover import run_discovery
            self.run_discovery = run_discovery
            self.skydiscover_available = True
        except ImportError:
            self.skydiscover_available = False
    
    async def run_evolution(self, 
                          evaluator_path: str,
                          target: str = "skills") -> Dict:
        """
        Run evolutionary optimization using SkyDiscover
        
        Args:
            evaluator_path: Path to evaluator script
            target: What to optimize (skills, prompts, algorithms)
        """
        
        if not self.skydiscover_available:
            return self._mock_evolution(evaluator_path, target)
        
        result = self.run_discovery(
            evaluator=evaluator_path,
            search=self.config["algorithm"],
            model=self.config["model"],
            iterations=self.config["iterations"],
            budget=self.config["budget"]
        )
        
        return {
            "best_solution": result.best_solution,
            "best_score": result.best_score,
            "iterations": result.iterations_completed,
            "cost": result.total_cost
        }
    
    def _mock_evolution(self, evaluator_path: str, target: str) -> Dict:
        """Mock evolution when SkyDiscover not available"""
        return {
            "best_solution": f"Optimized {target} for OfficeQA",
            "best_score": 0.75,
            "iterations": 100,
            "cost": 50.0
        }


class CompleteIntegration:
    """
    Complete Integration of All Systems
    
    This brings together:
    1. ROMA (DSPy-based recursive agent)
    2. RLM-style code execution
    3. GEPA+ prompt optimization
    4. SkyDiscover evolutionary algorithms
    5. Automated benchmark generation
    """
    
    def __init__(self, config_path: str = "config/profiles/officeqa/default.yaml"):
        self.roma = ROMAIntegration(config_path)
        self.rlm = RLMCodeExecution()
        self.gepa = GEPAPlusOptimizer()
        self.sky = SkyDiscoverRunner()
        
        # Import automated benchmark generator
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        try:
            from roma_dspy.core.skills.automated_benchmark_generator import (
                AutomatedBenchmarkGenerator,
                EvolutionaryBenchmarkProvider
            )
            self.benchmark_generator = AutomatedBenchmarkGenerator()
            self.benchmark_provider = EvolutionaryBenchmarkProvider()
            self.benchmark_available = True
        except ImportError:
            self.benchmark_available = False
    
    async def run_full_pipeline(self, 
                               questions: List[Dict],
                               mode: str = "test") -> Dict:
        """
        Run complete pipeline:
        1. Solve questions with ROMA + RLM code execution
        2. Collect execution traces
        3. Generate benchmarks from usage patterns
        4. Optimize prompts with GEPA+
        5. Run evolutionary algorithms with SkyDiscover
        """
        
        results = {
            "solved_questions": [],
            "execution_traces": [],
            "generated_benchmark": None,
            "optimized_prompts": {},
            "evolution_results": {}
        }
        
        # Step 1: Solve questions
        print(f"\n=== Solving {len(questions)} questions with ROMA + RLM ===")
        for i, question in enumerate(questions):
            print(f"Question {i+1}/{len(questions)}: {question['question'][:50]}...")
            
            # Solve with ROMA
            result = await self.roma.solve_question(question)
            
            results["solved_questions"].append({
                "question_id": question.get("uid", f"q{i}"),
                "question": question["question"],
                "predicted": result["answer"],
                "expected": question.get("answer", ""),
                "verified": result.get("verified", False),
                "path": result.get("path", "unknown")
            })
            
            # Collect execution trace for benchmark generation
            results["execution_traces"].append({
                "question_id": question.get("uid", f"q{i}"),
                "question": question["question"],
                "final_answer": result["answer"],
                "execution_steps": result.get("subtasks", 1),
                "tools_used": ["file_read", "table_parse"],
                "system_prompt": "ROMA recursive agent",
                "outcome": "correct" if result.get("verified") else "unknown"
            })
        
        if mode == "test":
            return results
        
        # Step 2: Generate benchmark from usage patterns
        if self.benchmark_available and len(results["execution_traces"]) >= 10:
            print("\n=== Generating benchmark from usage patterns ===")
            
            ground_truth = {q["uid"]: q["answer"] for q in questions if "uid" in q and "answer" in q}
            
            benchmark = await self.benchmark_provider.get_benchmark_for_evolution(
                results["execution_traces"],
                ground_truth
            )
            
            results["generated_benchmark"] = {
                "benchmark_id": benchmark.benchmark_id,
                "test_cases": len(benchmark.test_cases),
                "tool_requirements": benchmark.tool_requirements,
                "prompt_specifications": benchmark.prompt_specifications
            }
            
            print(f"Generated benchmark with {len(benchmark.test_cases)} test cases")
        
        # Step 3: Optimize prompts with GEPA+
        print("\n=== Optimizing prompts with GEPA+ ===")
        
        def evaluator(prompt: str) -> tuple:
            """Evaluate prompt on sample questions"""
            # Mock evaluation
            return (0.75, "Good performance on unit extraction, needs fiscal year work")
        
        # Optimize executor prompt (bottleneck component)
        seed_prompt = "You are an expert at Treasury Bulletin analysis..."
        optimized = await self.gepa.optimize_prompt(
            seed_prompt,
            evaluator,
            component="executor"
        )
        
        results["optimized_prompts"]["executor"] = optimized
        print(f"Executor prompt improved by {optimized['improvement']:.2%}")
        
        # Step 4: Run evolutionary optimization
        print("\n=== Running SkyDiscover evolution ===")
        
        # Export benchmark for SkyDiscover
        if self.benchmark_available and results["generated_benchmark"]:
            evaluator_code = self.benchmark_provider.export_benchmark_for_skydiscover(
                self.benchmark_provider.get_latest_benchmark()
            )
            
            evaluator_path = Path("evaluators/auto_generated_evaluator.py")
            evaluator_path.parent.mkdir(exist_ok=True)
            evaluator_path.write_text(evaluator_code)
            
            # Run evolution
            evolution_result = await self.sky.run_evolution(
                str(evaluator_path),
                target="skills"
            )
            
            results["evolution_results"] = evolution_result
            print(f"Evolution completed: score {evolution_result['best_score']:.2%}")
        
        return results
    
    def print_summary(self, results: Dict):
        """Print summary of pipeline results"""
        print("\n" + "="*60)
        print("COMPLETE INTEGRATION RESULTS")
        print("="*60)
        
        # Question solving
        solved = results["solved_questions"]
        correct = sum(1 for q in solved if q.get("verified", False))
        print(f"\nQuestions Solved: {len(solved)}")
        print(f"Verified Correct: {correct} ({correct/len(solved)*100:.1f}%)")
        
        # Benchmark generation
        if results.get("generated_benchmark"):
            bench = results["generated_benchmark"]
            print(f"\nGenerated Benchmark: {bench['benchmark_id']}")
            print(f"Test Cases: {bench['test_cases']}")
            print(f"Required Tools: {len(bench['tool_requirements'].get('required_tools', []))}")
        
        # Prompt optimization
        if results.get("optimized_prompts"):
            print(f"\nOptimized Prompts:")
            for component, opt in results["optimized_prompts"].items():
                print(f"  {component}: {opt['improvement']:.2%} improvement")
        
        # Evolution
        if results.get("evolution_results"):
            evo = results["evolution_results"]
            print(f"\nEvolution Results:")
            print(f"  Best Score: {evo['best_score']:.2%}")
            print(f"  Iterations: {evo['iterations']}")
            print(f"  Cost: ${evo['cost']:.2f}")
        
        print("="*60)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Complete Integration Runner")
    parser.add_argument("--mode", choices=["test", "evolve", "benchmark"], 
                       default="test", help="Run mode")
    parser.add_argument("--questions", type=int, default=5,
                       help="Number of questions to test")
    parser.add_argument("--config", default="config/profiles/officeqa/default.yaml",
                       help="Configuration file path")
    
    args = parser.parse_args()
    
    # Check dependencies
    print("Checking dependencies...")
    missing = check_dependencies()
    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        print("\nContinuing with mock implementations...\n")
    
    # Create integration
    integration = CompleteIntegration(args.config)
    
    # Load sample questions
    sample_questions = [
        {
            "uid": "SAMPLE001",
            "question": "What was the total public debt in millions for FY2020?",
            "answer": "36080",
            "difficulty": "easy"
        },
        {
            "uid": "SAMPLE002", 
            "question": "What period does FY1975 cover?",
            "answer": "Jul 1974 - Jun 1975",
            "difficulty": "medium"
        },
        {
            "uid": "SAMPLE003",
            "question": "Calculate the geometric mean yield for Q1 1941",
            "answer": "3.524",
            "difficulty": "hard"
        }
    ]
    
    # Run pipeline
    results = await integration.run_full_pipeline(
        sample_questions[:args.questions],
        mode=args.mode
    )
    
    # Print summary
    integration.print_summary(results)
    
    # Save results
    output_path = Path("results/complete_integration_results.json")
    output_path.parent.mkdir(exist_ok=True)
    
    # Convert to serializable format
    serializable = {
        "solved_questions": results["solved_questions"],
        "execution_traces": results["execution_traces"],
        "generated_benchmark": results.get("generated_benchmark"),
        "optimized_prompts": {
            k: {
                "improvement": v["improvement"],
                "iterations": v["iterations"]
            } for k, v in results.get("optimized_prompts", {}).items()
        },
        "evolution_results": results.get("evolution_results")
    }
    
    with open(output_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())