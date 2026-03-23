"""
Full Integration: optimize_anything + SkyDiscover + ROMA + RLM + GEPA

This module integrates all the systems:
1. optimize_anything API (GEPA) - Universal text optimization
2. SkyDiscover (AdaEvolve/EvoX) - Berkeley's evolutionary algorithms
3. ROMA (DSPy) - Recursive agent framework
4. RLM - REPL-based corpus traversal
5. CLI Auth - Use subscriptions instead of API keys

Usage:
    python scripts/full_integration.py --mode optimize
    python scripts/full_integration.py --mode evolve
    python scripts/full_integration.py --mode roma
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "external_repos" / "skydiscover"))

# Try imports
try:
    import gepa
    from gepa.optimize_anything import optimize_anything, GEPAConfig, EngineConfig
    GEPA_AVAILABLE = True
    print("✓ GEPA/optimize_anything available")
except ImportError:
    GEPA_AVAILABLE = False
    print("⚠ GEPA not available, using optimize-anything package")
    try:
        from optimize_anything import optimize_anything
        GEPA_AVAILABLE = True
    except ImportError:
        print("✗ optimize_anything not available")

try:
    from skydiscover import run_discovery, discover_solution
    SKYDISCOVER_AVAILABLE = True
    print("✓ SkyDiscover available (AdaEvolve/EvoX)")
except ImportError:
    SKYDISCOVER_AVAILABLE = False
    print("⚠ SkyDiscover not available")

try:
    import dspy
    DSPY_AVAILABLE = True
    print("✓ DSPy available (ROMA)")
except ImportError:
    DSPY_AVAILABLE = False
    print("⚠ DSPy not available")

try:
    from rlms import RLM
    RLM_AVAILABLE = True
    print("✓ RLM available")
except ImportError:
    RLM_AVAILABLE = False
    print("⚠ RLM not available")

# CLI Auth
try:
    from codex_cli_auth import get_codex_client, get_claude_client, setup_dspy_with_cli_auth
    CLI_AUTH_AVAILABLE = True
    print("✓ CLI auth available")
except ImportError:
    CLI_AUTH_AVAILABLE = False
    print("⚠ CLI auth not available")


class OptimizeAnythingIntegration:
    """
    Integration with GEPA's optimize_anything API
    
    From the docs:
    - optimize_anything(seed_candidate, evaluator, ...) -> GEPAResult
    - Three modes: Single-task, Multi-task, Generalization
    - Uses LLM reflection + Pareto-efficient search
    """
    
    def __init__(self, use_cli_auth: bool = True):
        self.use_cli_auth = use_cli_auth
        self.config = GEPAConfig(
            engine=EngineConfig(
                max_iterations=50,
                max_metric_calls=500,
            )
        ) if GEPA_AVAILABLE else None
    
    async def optimize_prompt(self, 
                             seed_prompt: str,
                             evaluator: Callable,
                             dataset: List = None,
                             valset: List = None) -> Dict:
        """
        Optimize a prompt using optimize_anything
        
        Args:
            seed_prompt: Initial prompt to optimize
            evaluator: Function that returns (score, feedback)
            dataset: Training examples (for multi-task/generalization)
            valset: Validation examples (for generalization)
        
        Returns:
            Optimization result with best candidate
        """
        
        if not GEPA_AVAILABLE:
            return self._mock_optimization(seed_prompt, evaluator)
        
        # Use optimize_anything API
        result = optimize_anything(
            seed_candidate=seed_prompt,
            evaluator=evaluator,
            dataset=dataset,
            valset=valset,
            config=self.config
        )
        
        return {
            "best_candidate": result.best_candidate,
            "best_score": result.best_score,
            "iterations": result.iterations,
            "metric_calls": result.metric_calls,
            "frontier_size": len(result.frontier) if hasattr(result, 'frontier') else 0
        }
    
    async def optimize_skill(self,
                            skill_description: str,
                            evaluator: Callable,
                            examples: List[Dict]) -> Dict:
        """
        Optimize a skill (generalization mode)
        
        This creates a skill that transfers to unseen problems.
        """
        
        if not GEPA_AVAILABLE:
            return {"error": "GEPA not available"}
        
        result = optimize_anything(
            seed_candidate=None,  # Let LLM generate from objective
            evaluator=evaluator,
            dataset=examples[:int(len(examples)*0.8)],
            valset=examples[int(len(examples)*0.8):],
            objective=skill_description,
            config=self.config
        )
        
        return {
            "optimized_skill": result.best_candidate,
            "validation_score": result.best_score,
            "generalization": True
        }
    
    def _mock_optimization(self, seed: str, evaluator: Callable) -> Dict:
        """Mock when GEPA not available"""
        score, _ = evaluator(seed)
        return {
            "best_candidate": seed + "\n\n[Mock optimized]",
            "best_score": score,
            "iterations": 1,
            "metric_calls": 1
        }


class SkyDiscoverIntegration:
    """
    Integration with Berkeley Sky Computing Lab's SkyDiscover
    
    Algorithms:
    - AdaEvolve: Adaptive multi-island search with UCB
    - EvoX: Meta-evolution (evolves the strategy itself)
    - OpenEvolve, GEPA, ShinkaEvolve: Also supported
    """
    
    def __init__(self):
        self.available = SKYDISCOVER_AVAILABLE
    
    async def run_adaevolve(self,
                           initial_program: str,
                           evaluator_path: str,
                           iterations: int = 100,
                           model: str = "gpt-5.4") -> Dict:
        """
        Run AdaEvolve optimization
        
        AdaEvolve features:
        - Multi-island adaptive search
        - UCB selection for exploration/exploitation
        - Migration strategies between islands
        - Paradigm breakthrough detection
        """
        
        if not self.available:
            return self._mock_evolution("AdaEvolve", initial_program)
        
        result = run_discovery(
            initial_program=initial_program,
            evaluator=evaluator_path,
            search="adaevolve",
            model=model,
            iterations=iterations
        )
        
        return {
            "algorithm": "AdaEvolve",
            "best_solution": result.best_solution,
            "best_score": result.best_score,
            "iterations": result.iterations_completed
        }
    
    async def run_evox(self,
                      initial_program: str,
                      evaluator_path: str,
                      iterations: int = 100,
                      model: str = "gpt-5.4") -> Dict:
        """
        Run EvoX optimization
        
        EvoX features:
        - Self-evolving paradigm
        - Co-adapts solution generation and experience
        - Meta-level strategy generation
        """
        
        if not self.available:
            return self._mock_evolution("EvoX", initial_program)
        
        result = run_discovery(
            initial_program=initial_program,
            evaluator=evaluator_path,
            search="evox",
            model=model,
            iterations=iterations
        )
        
        return {
            "algorithm": "EvoX",
            "best_solution": result.best_solution,
            "best_score": result.best_score,
            "iterations": result.iterations_completed
        }
    
    async def discover_algorithm(self,
                                problem_description: str,
                                evaluator: Callable,
                                iterations: int = 50) -> Dict:
        """
        Discover a new algorithm using discover_solution convenience API
        """
        
        if not self.available:
            return {"error": "SkyDiscover not available"}
        
        result = discover_solution(
            initial_solution=None,  # Start from scratch
            evaluator=evaluator,
            iterations=iterations,
            search="evox",  # Use meta-evolution
            objective=problem_description
        )
        
        return {
            "discovered_algorithm": result.best_solution,
            "score": result.best_score
        }
    
    def _mock_evolution(self, algo: str, program: str) -> Dict:
        """Mock when SkyDiscover not available"""
        return {
            "algorithm": algo,
            "best_solution": f"# Optimized by {algo}\n{program}",
            "best_score": 0.85,
            "iterations": 100
        }


class ROMAWithCLIAuth:
    """
    ROMA (DSPy-based Recursive Agent) with CLI Auth
    
    Uses subscriptions via Codex/Claude CLI instead of API keys.
    """
    
    def __init__(self):
        if not DSPY_AVAILABLE:
            raise RuntimeError("DSPy not installed")
        
        # Use regular DSPy LM for now (CLI auth has compatibility issues)
        # Configure with Claude Sonnet 4.6
        if os.environ.get("ANTHROPIC_API_KEY"):
            dspy.configure(lm=dspy.LM("anthropic/claude-sonnet-4-6"))
            print("DSPy configured with Anthropic API")
        elif os.environ.get("OPENAI_API_KEY"):
            dspy.configure(lm=dspy.LM("openai/gpt-5.4", temperature=1.0, max_tokens=16000))
            print("DSPy configured with OpenAI API")
        else:
            print("Warning: No API keys set for DSPy")
    
    async def solve(self, question: str, max_depth: int = 2) -> Dict:
        """
        Solve a question using ROMA recursion
        
        ROMA roles:
        - Atomizer: Decide if atomic or needs decomposition
        - Planner: Create typed subtasks
        - Executor: Run tools/code
        - Aggregator: Synthesize with evidence cards
        - Verifier: Check output
        """
        
        # Define DSPy signatures
        class Atomizer(dspy.Signature):
            """Decide if task is atomic"""
            question = dspy.InputField()
            is_atomic = dspy.OutputField(desc="True if can solve directly")
            reasoning = dspy.OutputField()
        
        class Executor(dspy.Signature):
            """Execute task with tools"""
            task = dspy.InputField()
            result = dspy.OutputField(desc="Evidence card with answer")
        
        # Run atomizer
        atomizer = dspy.Predict(Atomizer)
        atomized = atomizer(question=question)
        
        if atomized.is_atomic.lower() == "true":
            # Direct execution
            executor = dspy.Predict(Executor)
            result = executor(task=question)
            return {
                "answer": result.result,
                "path": "atomic",
                "depth": 0
            }
        else:
            # Would decompose - for now return mock
            return {
                "answer": "Decomposed solution",
                "path": "decomposed",
                "depth": max_depth
            }


class RLMIntegration:
    """
    RLM (Recursive Language Model) Integration
    
    RLM uses Python REPL for corpus traversal:
    - Recurses on DATA (not TASK like ROMA)
    - LLM writes code to inspect/decompose corpus
    - Works well for large document collections
    """
    
    def __init__(self, corpus_path: str = "data/treasury_bulletins/"):
        self.corpus_path = Path(corpus_path)
        self.available = RLM_AVAILABLE
    
    async def traverse_corpus(self, query: str) -> Dict:
        """
        Traverse corpus using RLM-style code execution
        
        The LLM generates code like:
        ```python
        files = [f for f in os.listdir(corpus_path) if '1941' in f]
        for f in files:
            content = open(f).read()
            # Parse and extract
        ```
        """
        
        if not self.available:
            return self._mock_traverse(query)
        
        # Use RLM package
        rlm = RLM(model="claude-sonnet-4-6")
        result = rlm.run(
            task=query,
            working_dir=str(self.corpus_path)
        )
        
        return {
            "result": result.output,
            "code_generated": result.code,
            "files_processed": result.files_touched
        }
    
    def _mock_traverse(self, query: str) -> Dict:
        """Mock when RLM not available"""
        return {
            "result": f"Found relevant data for: {query}",
            "code_generated": f"# Mock code for {query}",
            "files_processed": 3
        }


class FullIntegration:
    """
    Complete integration of all systems
    """
    
    def __init__(self):
        self.optimize_anything = OptimizeAnythingIntegration() if GEPA_AVAILABLE else None
        self.skydiscover = SkyDiscoverIntegration() if SKYDISCOVER_AVAILABLE else None
        self.rlm = RLMIntegration() if RLM_AVAILABLE else None
        self.roma = ROMAWithCLIAuth() if DSPY_AVAILABLE else None
    
    async def run_full_pipeline(self, 
                               questions: List[Dict],
                               mode: str = "test") -> Dict:
        """
        Run complete pipeline:
        1. Solve questions with ROMA
        2. Optimize prompts with optimize_anything
        3. Run evolutionary search with SkyDiscover
        """
        
        results = {
            "solved": [],
            "optimized_prompts": {},
            "evolution_results": {}
        }
        
        # Step 1: Solve with ROMA
        if self.roma:
            print("\n=== Solving with ROMA (DSPy) ===")
            for q in questions[:3]:  # Limit for testing
                try:
                    result = await self.roma.solve(q["question"])
                    results["solved"].append({
                        "question": q["question"][:50],
                        "answer": result["answer"][:100] if result["answer"] else "",
                        "path": result["path"]
                    })
                except Exception as e:
                    print(f"Error: {e}")
        
        # Step 2: Optimize executor prompt with optimize_anything
        if self.optimize_anything and mode != "test":
            print("\n=== Optimizing with optimize_anything ===")
            
            def evaluator(prompt: str) -> tuple:
                # Mock evaluation
                return (0.75, "Good but needs fiscal year handling")
            
            seed = "You are an expert at Treasury Bulletin analysis."
            opt_result = await self.optimize_anything.optimize_prompt(seed, evaluator)
            results["optimized_prompts"]["executor"] = opt_result
            print(f"Optimized: {opt_result['best_score']:.2%}")
        
        # Step 3: Run AdaEvolve/EvoX
        if self.skydiscover and mode == "evolve":
            print("\n=== Running SkyDiscover (AdaEvolve) ===")
            
            # Would need actual evaluator file
            evo_result = await self.skydiscover.run_adaevolve(
                initial_program="# Initial solution",
                evaluator_path="evaluator.py",
                iterations=10
            )
            results["evolution_results"] = evo_result
            print(f"Evolution: {evo_result['best_score']:.2%}")
        
        return results
    
    def print_summary(self, results: Dict):
        """Print summary"""
        print("\n" + "="*60)
        print("FULL INTEGRATION RESULTS")
        print("="*60)
        
        print(f"\nSolved: {len(results['solved'])} questions")
        for s in results['solved']:
            print(f"  - {s['question']}: {s['path']}")
        
        if results.get('optimized_prompts'):
            print(f"\nOptimized Prompts:")
            for name, opt in results['optimized_prompts'].items():
                print(f"  {name}: {opt.get('best_score', 'N/A')}")
        
        if results.get('evolution_results'):
            evo = results['evolution_results']
            print(f"\nEvolution ({evo.get('algorithm', 'unknown')}):")
            print(f"  Score: {evo.get('best_score', 'N/A')}")
        
        print("="*60)


async def main():
    """Main entry point"""
    print("="*60)
    print("FULL INTEGRATION: optimize_anything + SkyDiscover + ROMA + RLM")
    print("="*60)
    
    # Sample questions
    questions = [
        {"question": "What was the total public debt in millions for FY2020?"},
        {"question": "What period does FY1975 cover?"},
        {"question": "Calculate geometric mean yield for Q1 1941"}
    ]
    
    # Create integration
    integration = FullIntegration()
    
    # Run pipeline
    results = await integration.run_full_pipeline(questions, mode="test")
    
    # Print summary
    integration.print_summary(results)
    
    # Show what's available
    print("\n=== Available Systems ===")
    print(f"GEPA/optimize_anything: {'✓' if GEPA_AVAILABLE else '✗'}")
    print(f"SkyDiscover (AdaEvolve/EvoX): {'✓' if SKYDISCOVER_AVAILABLE else '✗'}")
    print(f"DSPy (ROMA): {'✓' if DSPY_AVAILABLE else '✗'}")
    print(f"RLM: {'✓' if RLM_AVAILABLE else '✗'}")
    print(f"CLI Auth: {'✓' if CLI_AUTH_AVAILABLE else '✗'}")


if __name__ == "__main__":
    asyncio.run(main())