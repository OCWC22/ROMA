"""
CLI-Only Integration - NO API KEYS

Uses Codex CLI and Claude CLI for all LLM calls.
Works with subscriptions, not API credits.

Systems integrated:
1. DSPy/ROMA - via CLI subprocess calls
2. optimize_anything/GEPA - via CLI subprocess calls  
3. SkyDiscover (AdaEvolve/EvoX) - via CLI subprocess calls
4. RLM - via CLI subprocess calls

Usage:
    python scripts/cli_only_integration.py --mode test
    python scripts/cli_only_integration.py --mode optimize
    python scripts/cli_only_integration.py --mode evolve
"""

import subprocess
import json
import os
import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Add SkyDiscover path
sys.path.insert(0, str(Path(__file__).parent.parent / "external_repos" / "skydiscover"))


@dataclass
class CLIResponse:
    """Response from CLI tool"""
    success: bool
    output: str
    error: str = ""
    model: str = ""
    tokens_used: int = 0


class CodexCLI:
    """
    OpenAI Codex CLI wrapper
    
    Uses subscription via CLI, not API keys.
    """
    
    def __init__(self, model: str = "gpt-5.4"):
        self.model = model
        self._check_installed()
    
    def _check_installed(self):
        """Check if Codex CLI is installed"""
        try:
            result = subprocess.run(
                ["codex", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"✓ Codex CLI available")
            else:
                print("⚠ Codex CLI not authenticated - run: codex login")
        except FileNotFoundError:
            raise RuntimeError("Codex CLI not installed. Run: npm install -g @openai/codex")
    
    def chat(self, prompt: str, model: str = None) -> CLIResponse:
        """Send chat message via Codex CLI"""
        model = model or self.model
        
        # Codex CLI: codex exec "prompt" --model gpt-5.4
        result = subprocess.run(
            ["codex", "exec", prompt, "--model", model],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode == 0:
            return CLIResponse(
                success=True,
                output=result.stdout,
                model=model
            )
        else:
            return CLIResponse(success=False, output="", error=result.stderr, model=model)
    
    def run_task(self, task: str, model: str = None) -> CLIResponse:
        """Run agentic task via Codex CLI"""
        model = model or self.model
        
        result = subprocess.run(
            ["codex", "exec", task, "--model", model],
            capture_output=True, text=True, timeout=300
        )
        
        return CLIResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else "",
            model=model
        )


class ClaudeCLI:
    """
    Anthropic Claude CLI wrapper
    
    Uses subscription via CLI, not API keys.
    """
    
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        self._check_installed()
    
    def _check_installed(self):
        """Check if Claude CLI is installed"""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"✓ Claude CLI available")
            else:
                print("⚠ Claude CLI not authenticated - run: claude login")
        except FileNotFoundError:
            raise RuntimeError("Claude CLI not installed. Run: npm install -g @anthropic-ai/claude-code")
    
    def chat(self, prompt: str, model: str = None) -> CLIResponse:
        """Send chat message via Claude CLI"""
        model = model or self.model
        
        # Claude CLI uses --print for non-interactive mode
        self.timeout = 300  # 5 minutes for complex tasks
        
        result = subprocess.run(
            ["claude", "--print", "--model", model, prompt],
            capture_output=True, text=True, timeout=self.timeout
        )
        
        return CLIResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else "",
            model=model
        )
    
    def run_task(self, task: str, model: str = None) -> CLIResponse:
        """Run agentic task via Claude CLI"""
        model = model or self.model
        
        result = subprocess.run(
            ["claude", "--print", "--model", model, task],
            capture_output=True, text=True, timeout=300
        )
        
        return CLIResponse(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else "",
            model=model
        )


class DSPyCLI:
    """
    DSPy-compatible interface using CLI tools
    
    This replaces dspy.LM with CLI calls.
    No API keys needed - uses subscriptions.
    """
    
    def __init__(self, provider: str = "anthropic", model: str = None):
        self.provider = provider
        
        if provider == "openai":
            self.cli = CodexCLI(model or "gpt-5.4")
        else:
            self.cli = ClaudeCLI(model or "claude-sonnet-4-6")
        
        print(f"✓ DSPy configured with {provider} CLI")
    
    def __call__(self, prompt: str, **kwargs) -> str:
        """Make DSPy-compatible call via CLI"""
        response = self.cli.chat(prompt, model=kwargs.get("model"))
        if response.success:
            return response.output
        else:
            raise RuntimeError(f"CLI call failed: {response.error}")


class OptimizeAnythingCLI:
    """
    optimize_anything using CLI tools
    
    GEPA's optimize_anything API but with CLI auth.
    """
    
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider
        
        if provider == "openai":
            self.cli = CodexCLI("gpt-5.4")
        else:
            self.cli = ClaudeCLI("claude-sonnet-4-6")
        
        print(f"✓ optimize_anything configured with {provider} CLI")
    
    async def optimize(self,
                      seed_candidate: str,
                      evaluator: callable,
                      iterations: int = 20) -> Dict:
        """
        Optimize using CLI-based reflection
        
        1. Evaluate seed candidate
        2. Use CLI to reflect on feedback
        3. Generate improved candidate
        4. Repeat
        """
        
        current = seed_candidate
        best_score = 0
        best_candidate = current
        history = []
        
        for i in range(iterations):
            # Evaluate current candidate
            score, feedback = evaluator(current)
            
            history.append({
                "iteration": i,
                "score": score,
                "candidate": current[:100] + "..."
            })
            
            if score > best_score:
                best_score = score
                best_candidate = current
            
            # Use CLI to reflect and improve
            reflect_prompt = f"""
You are optimizing a text artifact. Current version:

{current}

Evaluation score: {score}
Feedback: {feedback}

Generate an improved version that addresses the feedback.
Only output the improved artifact, no explanations.
"""
            
            response = self.cli.chat(reflect_prompt)
            if response.success:
                current = response.output.strip()
            else:
                print(f"Warning: CLI reflection failed: {response.error}")
        
        return {
            "best_candidate": best_candidate,
            "best_score": best_score,
            "iterations": iterations,
            "history": history
        }


class SkyDiscoverCLI:
    """
    SkyDiscover (AdaEvolve/EvoX) using CLI tools
    
    Berkeley's evolutionary algorithms with CLI auth.
    """
    
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider
        
        # SkyDiscover needs to be configured to use CLI
        self.skydiscover_path = Path(__file__).parent.parent / "external_repos" / "skydiscover"
        
        if provider == "openai":
            self.model = "gpt-5.4"
        else:
            self.model = "claude-sonnet-4-6"
        
        print(f"✓ SkyDiscover configured with {provider} CLI")
    
    async def run_adaevolve(self,
                           initial_program: str,
                           evaluator_code: str,
                           iterations: int = 50) -> Dict:
        """
        Run AdaEvolve via CLI
        
        AdaEvolve features:
        - Multi-island adaptive search
        - UCB selection for exploration/exploitation
        - Migration strategies
        """
        
        # Create temp files for SkyDiscover
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            program_path = Path(tmpdir) / "program.py"
            evaluator_path = Path(tmpdir) / "evaluator.py"
            
            program_path.write_text(initial_program)
            evaluator_path.write_text(evaluator_code)
            
            # Run SkyDiscover with CLI auth
            # SkyDiscover uses environment variables, but we can override
            env = os.environ.copy()
            # Don't set API keys - SkyDiscover will need to be configured for CLI
            
            result = subprocess.run(
                ["uv", "run", "skydiscover-run",
                 str(program_path), str(evaluator_path),
                 "--search", "adaevolve",
                 "--model", self.model,
                 "--iterations", str(iterations)],
                cwd=str(self.skydiscover_path),
                capture_output=True, text=True, timeout=600,
                env=env
            )
            
            return {
                "algorithm": "AdaEvolve",
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
                "success": result.returncode == 0
            }
    
    async def run_evox(self,
                      initial_program: str,
                      evaluator_code: str,
                      iterations: int = 50) -> Dict:
        """
        Run EvoX via CLI
        
        EvoX features:
        - Self-evolving paradigm
        - Meta-level strategy generation
        """
        
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            program_path = Path(tmpdir) / "program.py"
            evaluator_path = Path(tmpdir) / "evaluator.py"
            
            program_path.write_text(initial_program)
            evaluator_path.write_text(evaluator_code)
            
            result = subprocess.run(
                ["uv", "run", "skydiscover-run",
                 str(program_path), str(evaluator_path),
                 "--search", "evox",
                 "--model", self.model,
                 "--iterations", str(iterations)],
                cwd=str(self.skydiscover_path),
                capture_output=True, text=True, timeout=600
            )
            
            return {
                "algorithm": "EvoX",
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else "",
                "success": result.returncode == 0
            }


class ROMAWithCLI:
    """
    ROMA (Recursive Open Meta-Agent) using CLI tools
    
    DSPy-based recursive agent but with CLI auth.
    """
    
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider
        
        if provider == "openai":
            self.cli = CodexCLI("gpt-5.4")
            self.executor_model = "gpt-5.4"
        else:
            self.cli = ClaudeCLI("claude-sonnet-4-6")
            self.executor_model = "claude-sonnet-4-6"
        
        # Use cheaper models for simple roles
        if provider == "openai":
            self.atomizer = CodexCLI("gpt-5.3-chat-latest")
            self.executor_model = "gpt-5.4"
        else:
            self.atomizer = ClaudeCLI("claude-haiku-4-5")
            self.executor_model = "claude-haiku-4-5"  # Use Haiku for speed
        
        # Increase timeout for executor
        self.cli.timeout = 300
        
        print(f"✓ ROMA configured with {provider} CLI")
    
    async def solve(self, question: str, max_depth: int = 2) -> Dict:
        """
        Solve using ROMA recursion via CLI
        
        Roles:
        - Atomizer: Decide if atomic or decompose
        - Planner: Create typed subtasks
        - Executor: Run tools/code
        - Aggregator: Synthesize with evidence cards
        - Verifier: Check output
        """
        
        # Step 1: Atomize
        atomize_prompt = f"""
Decide if this question can be answered directly (atomic) or needs decomposition.

Question: {question}

Respond with either:
ATOMIC: <brief reasoning>
or
DECOMPOSE: <list of subtasks>
"""
        
        atomize_response = self.atomizer.chat(atomize_prompt)
        
        if not atomize_response.success:
            return {"error": f"Atomization failed: {atomize_response.error}", "path": "error"}
        
        atomize_output = atomize_response.output.upper()
        
        if "ATOMIC" in atomize_output:
            # Direct execution
            exec_prompt = f"""
You are an expert at Treasury Bulletin analysis.

Question: {question}

Answer the question. If you need to extract data from tables:
1. NEVER expand units - if header says "in millions", keep base number (e.g., 36080 not 36080000000)
2. Cite the source file and page
3. Format as YAML evidence card

Output the answer and evidence card.
"""
            
            exec_response = self.cli.chat(exec_prompt, model=self.executor_model)
            
            return {
                "answer": exec_response.output,
                "path": "atomic",
                "depth": 0,
                "evidence_card": self._extract_evidence_card(exec_response.output)
            }
        else:
            # Decompose and solve subtasks
            subtasks = self._parse_subtasks(atomize_response.output)
            
            subtask_results = []
            for subtask in subtasks[:3]:  # Limit to 3 subtasks
                result = self.cli.chat(f"Subtask: {subtask}\n\nProvide result as evidence card.")
                subtask_results.append(result.output if result.success else "Failed")
            
            # Aggregate
            agg_prompt = f"""
Aggregate these subtask results into a final answer:

Subtasks: {subtasks}
Results: {subtask_results}

Original question: {question}

Provide final answer with evidence card.
"""
            
            final_response = self.cli.chat(agg_prompt)
            
            return {
                "answer": final_response.output,
                "path": "decomposed",
                "depth": 1,
                "subtasks": len(subtasks),
                "subtask_results": subtask_results
            }
    
    def _parse_subtasks(self, text: str) -> List[str]:
        """Parse subtasks from decompose output"""
        lines = text.split("\n")
        subtasks = []
        for line in lines:
            if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                subtasks.append(line.strip())
        return subtasks if subtasks else ["Decompose further"]
    
    def _extract_evidence_card(self, text: str) -> str:
        """Extract evidence card from output"""
        if "evidence_card:" in text.lower():
            start = text.lower().find("evidence_card:")
            return text[start:start+500]
        return ""


class FullCLIIntegration:
    """
    Complete integration using ONLY CLI tools
    
    No API keys - uses subscriptions via Codex/Claude CLI.
    """
    
    def __init__(self, provider: str = "anthropic"):
        self.provider = provider
        
        # Initialize all systems with CLI
        self.dspy = DSPyCLI(provider)
        self.optimize_anything = OptimizeAnythingCLI(provider)
        self.skydiscover = SkyDiscoverCLI(provider)
        self.roma = ROMAWithCLI(provider)
        
        print(f"\n✓ All systems configured with {provider} CLI (no API keys)")
    
    async def run_full_pipeline(self, questions: List[str], mode: str = "test") -> Dict:
        """
        Run complete pipeline:
        1. Solve with ROMA
        2. Optimize prompts with optimize_anything
        3. Evolve with SkyDiscover
        """
        
        results = {
            "solved": [],
            "optimized": {},
            "evolved": {}
        }
        
        # Step 1: Solve with ROMA
        print("\n=== Solving with ROMA (CLI) ===")
        for q in questions[:3]:
            try:
                result = await self.roma.solve(q)
                results["solved"].append({
                    "question": q[:50],
                    "answer": result.get("answer", "")[:100],
                    "path": result.get("path", "unknown")
                })
                print(f"  ✓ {q[:40]}... -> {result.get('path', 'unknown')}")
            except Exception as e:
                print(f"  ✗ {q[:40]}... -> Error: {e}")
        
        # Step 2: Optimize executor prompt
        if mode in ["optimize", "evolve"]:
            print("\n=== Optimizing with optimize_anything (CLI) ===")
            
            def evaluator(prompt: str) -> tuple:
                # Mock evaluation - in reality would run on test set
                score = 0.7 if "treasury" in prompt.lower() else 0.5
                feedback = "Add fiscal year handling" if score < 0.8 else "Good"
                return (score, feedback)
            
            seed_prompt = "You are an expert at Treasury Bulletin analysis."
            
            opt_result = await self.optimize_anything.optimize(
                seed_prompt, evaluator, iterations=5
            )
            
            results["optimized"]["executor"] = opt_result
            print(f"  ✓ Optimized to score: {opt_result['best_score']:.2%}")
        
        # Step 3: Run evolutionary search
        if mode == "evolve":
            print("\n=== Running SkyDiscover (CLI) ===")
            
            initial_program = '''
def solve(question):
    # Initial solution
    return "Answer not found"
'''
            
            evaluator_code = '''
def evaluate(program_path):
    # Load and test program
    return {"combined_score": 0.5}
'''
            
            evo_result = await self.skydiscover.run_adaevolve(
                initial_program, evaluator_code, iterations=10
            )
            
            results["evolved"] = evo_result
            print(f"  ✓ AdaEvolve: {evo_result.get('success', False)}")
        
        return results
    
    def print_summary(self, results: Dict):
        """Print summary"""
        print("\n" + "="*60)
        print("CLI-ONLY INTEGRATION RESULTS")
        print("="*60)
        
        print(f"\nSolved: {len(results['solved'])} questions")
        for s in results['solved']:
            print(f"  - {s['question']}: {s['path']}")
        
        if results.get('optimized'):
            print(f"\nOptimized Prompts:")
            for name, opt in results['optimized'].items():
                print(f"  {name}: {opt.get('best_score', 'N/A'):.2%}")
        
        if results.get('evolved'):
            evo = results['evolved']
            print(f"\nEvolution ({evo.get('algorithm', 'unknown')}):")
            print(f"  Success: {evo.get('success', False)}")
        
        print("="*60)


async def main():
    """Main entry point"""
    
    print("="*60)
    print("CLI-ONLY INTEGRATION")
    print("Using subscriptions via Codex/Claude CLI")
    print("NO API KEYS REQUIRED")
    print("="*60)
    
    # Check CLI tools are installed
    print("\nChecking CLI tools...")
    
    cli_tools_ok = True
    
    try:
        result = subprocess.run(["codex", "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            print("✓ Codex CLI installed")
        else:
            print("⚠ Codex CLI not authenticated - run: codex login")
    except FileNotFoundError:
        print("✗ Codex CLI not installed - run: npm install -g @openai/codex")
        cli_tools_ok = False
    
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            print("✓ Claude CLI installed")
        else:
            print("⚠ Claude CLI not authenticated - run: claude login")
    except FileNotFoundError:
        print("✗ Claude CLI not installed - run: npm install -g @anthropic-ai/claude-code")
        cli_tools_ok = False
    
    if not cli_tools_ok:
        print("\nPlease install CLI tools first:")
        print("  npm install -g @openai/codex")
        print("  npm install -g @anthropic-ai/claude-code")
        print("\nThen authenticate:")
        print("  codex login")
        print("  claude login")
        return
    
    # Sample questions
    questions = [
        "What was the total public debt in millions for FY2020?",
        "What period does FY1975 cover?",
        "Calculate geometric mean yield for Q1 1941"
    ]
    
    # Create integration (defaults to Claude CLI)
    integration = FullCLIIntegration(provider="anthropic")
    
    # Run pipeline
    results = await integration.run_full_pipeline(questions, mode="test")
    
    # Print summary
    integration.print_summary(results)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["test", "optimize", "evolve"], default="test")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="anthropic")
    args = parser.parse_args()
    
    asyncio.run(main())