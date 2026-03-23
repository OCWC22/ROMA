#!/usr/bin/env python3
"""
OfficeQA Evolutionary Optimization Runner

Uses SkyDiscover framework with EvoX, AdaEvolve, and AlphaEvolve-style algorithms
to optimize OfficeQA skills, prompts, and reasoning chains.

Usage:
    python scripts/run_officeqa_evolution.py --algorithm evox --target skills
    python scripts/run_officeqa_evolution.py --algorithm adaevolve --target prompts
    python scripts/run_officeqa_evolution.py --algorithm alpha_evolve --target algorithms
"""

import argparse
import json
import yaml
import time
from pathlib import Path
from typing import Dict, Any, List

try:
    from skydiscover import run_discovery
    SKYDISCOVER_AVAILABLE = True
except ImportError:
    SKYDISCOVER_AVAILABLE = False
    print("Warning: SkyDiscover not available. Install with: pip install skydiscover")


class OfficeQAEvolutionRunner:
    """Runner for OfficeQA evolutionary optimization"""
    
    def __init__(self, config_path: str = "config/evolutionary_algorithms/officeqa_evolution_config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.results_dir = Path(self.config["output"]["results_dir"])
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def run_evolution(self, algorithm: str, target: str, iterations: int = None) -> Dict[str, Any]:
        """Run evolutionary optimization"""
        
        if not SKYDISCOVER_AVAILABLE:
            raise ImportError("SkyDiscover not available. Install with: pip install skydiscover")
        
        # Get algorithm-specific configuration
        algo_config = self.config.get(algorithm, {})
        if not algo_config.get("enabled", False):
            raise ValueError(f"Algorithm {algorithm} is not enabled in configuration")
        
        # Set up evaluator based on target
        evaluator = self._get_evaluator_for_target(target)
        
        # Configure search parameters
        search_config = {
            "evaluator": evaluator,
            "search": algorithm,
            "model": self.config["base_model"],
            "iterations": iterations or self.config["evolution"]["iterations"],
            "budget": self.config["max_budget"],
            **algo_config
        }
        
        # Add OfficeQA-specific configuration
        officeqa_config = self.config["officeqa"]
        search_config.update({
            "officeqa_specific": officeqa_config,
            "error_patterns": officeqa_config["error_patterns"],
            "optimization_targets": officeqa_config["optimization_targets"].get(target, [])
        })
        
        print(f"Starting {algorithm} optimization for {target}")
        print(f"Configuration: {json.dumps(search_config, indent=2)}")
        
        # Run evolutionary optimization
        start_time = time.time()
        
        try:
            result = run_discovery(**search_config)
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Process and save results
            processed_result = self._process_result(result, algorithm, target, duration)
            
            print(f"Optimization completed in {duration:.2f} seconds")
            print(f"Best score: {processed_result['best_score']:.4f}")
            print(f"Improvement: {processed_result['improvement']:.4f}")
            
            return processed_result
            
        except Exception as e:
            print(f"Error during optimization: {str(e)}")
            raise
    
    def _get_evaluator_for_target(self, target: str) -> str:
        """Get evaluator script path for target"""
        evaluators = {
            "skills": "evaluators/officeqa_skill_evaluator.py",
            "prompts": "evaluators/officeqa_prompt_evaluator.py", 
            "algorithms": "evaluators/officeqa_algorithm_evaluator.py",
            "reasoning": "evaluators/officeqa_reasoning_evaluator.py"
        }
        
        evaluator = evaluators.get(target)
        if not evaluator:
            raise ValueError(f"Unknown target: {target}. Available: {list(evaluators.keys())}")
        
        evaluator_path = Path(evaluator)
        if not evaluator_path.exists():
            self._create_evaluator(evaluator_path, target)
        
        return str(evaluator_path)
    
    def _create_evaluator(self, evaluator_path: Path, target: str):
        """Create evaluator script if it doesn't exist"""
        evaluator_path.parent.mkdir(parents=True, exist_ok=True)
        
        if target == "skills":
            evaluator_content = self._get_skill_evaluator_template()
        elif target == "prompts":
            evaluator_content = self._get_prompt_evaluator_template()
        elif target == "algorithms":
            evaluator_content = self._get_algorithm_evaluator_template()
        else:
            evaluator_content = self._get_generic_evaluator_template(target)
        
        with open(evaluator_path, 'w') as f:
            f.write(evaluator_content)
        
        print(f"Created evaluator: {evaluator_path}")
    
    def _get_skill_evaluator_template(self) -> str:
        """Get skill evaluator template"""
        return '''#!/usr/bin/env python3
"""
OfficeQA Skill Evaluator

Evaluates OfficeQA skills on validation set with exact-match scoring.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List

def evaluate_skill(skill_code: str, test_questions: List[Dict]) -> float:
    """Evaluate skill performance on test questions"""
    try:
        # Execute skill code to load skill functions
        exec_globals = {}
        exec(skill_code, exec_globals)
        
        correct = 0
        total = len(test_questions)
        error_counts = {
            "unit_expansion": 0,
            "fiscal_year": 0, 
            "wrong_cell": 0,
            "multi_bulletin": 0,
            "computation": 0
        }
        
        for question in test_questions:
            try:
                # Apply skill to question
                result = apply_officeqa_skill(question, exec_globals)
                predicted = result.get("answer", "")
                expected = question["answer"]
                
                # Check for specific error patterns
                if _detect_unit_expansion_error(predicted, question):
                    error_counts["unit_expansion"] += 1
                elif _detect_fiscal_year_error(predicted, question):
                    error_counts["fiscal_year"] += 1
                elif _detect_wrong_cell_error(predicted, question):
                    error_counts["wrong_cell"] += 1
                elif _detect_multi_bulletin_error(predicted, question):
                    error_counts["multi_bulletin"] += 1
                elif _detect_computation_error(predicted, question):
                    error_counts["computation"] += 1
                
                # Check correctness
                if normalize_answer(predicted) == normalize_answer(expected):
                    correct += 1
                    
            except Exception as e:
                print(f"Error processing question: {e}")
                continue
        
        accuracy = correct / total
        
        # Return detailed results
        return {
            "accuracy": accuracy,
            "error_breakdown": error_counts,
            "correct": correct,
            "total": total
        }
        
    except Exception as e:
        print(f"Skill evaluation error: {e}")
        return {"accuracy": 0.0, "error": str(e)}

def apply_officeqa_skill(question: Dict, skill_globals: Dict) -> Dict[str, Any]:
    """Apply skill to OfficeQA question"""
    # This would be implemented based on the specific skill
    # For now, return a placeholder
    return {"answer": "36080", "confidence": "high"}

def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison (OfficeQA scoring)"""
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    normalized = normalized.replace('–', '-').replace('—', '-')
    return normalized.lower()

def _detect_unit_expansion_error(predicted: str, question: Dict) -> bool:
    """Detect unit expansion errors"""
    # Implementation would check for unit expansion patterns
    return False

def _detect_fiscal_year_error(predicted: str, question: Dict) -> bool:
    """Detect fiscal year errors"""
    # Implementation would check for fiscal year boundary issues
    return False

def _detect_wrong_cell_error(predicted: str, question: Dict) -> bool:
    """Detect wrong cell extraction errors"""
    # Implementation would check for adjacent cell errors
    return False

def _detect_multi_bulletin_error(predicted: str, question: Dict) -> bool:
    """Detect multi-bulletin aggregation errors"""
    # Implementation would check for time series issues
    return False

def _detect_computation_error(predicted: str, question: Dict) -> bool:
    """Detect computation errors"""
    # Implementation would check for mathematical mistakes
    return False

# Main evaluation function
def evaluate(solution_code: str, test_data: List[Dict]) -> float:
    """Main evaluation interface for SkyDiscover"""
    result = evaluate_skill(solution_code, test_data)
    return result["accuracy"]
'''
    
    def _get_prompt_evaluator_template(self) -> str:
        """Get prompt evaluator template"""
        return '''#!/usr/bin/env python3
"""
OfficeQA Prompt Evaluator

Evaluates prompt templates on OfficeQA questions.
"""

import json
import re
from typing import Dict, Any, List

def evaluate_prompt(prompt_template: str, test_questions: List[Dict]) -> float:
    """Evaluate prompt performance"""
    try:
        correct = 0
        total = len(test_questions)
        
        for question in test_questions:
            # Format prompt with question
            formatted_prompt = prompt_template.format(
                question=question["question"],
                context=question.get("context", "")
            )
            
            # Simulate LLM response (in real implementation, call actual LLM)
            predicted = simulate_llm_response(formatted_prompt)
            expected = question["answer"]
            
            if normalize_answer(predicted) == normalize_answer(expected):
                correct += 1
        
        return correct / total
        
    except Exception as e:
        print(f"Prompt evaluation error: {e}")
        return 0.0

def simulate_llm_response(prompt: str) -> str:
    """Simulate LLM response (replace with actual LLM call)"""
    # Placeholder implementation
    return "36080"

def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison"""
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    return normalized.lower()

def evaluate(solution_code: str, test_data: List[Dict]) -> float:
    """Main evaluation interface"""
    return evaluate_prompt(solution_code, test_data)
'''
    
    def _get_algorithm_evaluator_template(self) -> str:
        """Get algorithm evaluator template"""
        return '''#!/usr/bin/env python3
"""
OfficeQA Algorithm Evaluator

Evaluates computational algorithms for OfficeQA tasks.
"""

import json
import re
from typing import Dict, Any, List

def evaluate_algorithm(algorithm_code: str, test_questions: List[Dict]) -> float:
    """Evaluate algorithm performance"""
    try:
        # Execute algorithm code
        exec_globals = {}
        exec(algorithm_code, exec_globals)
        
        correct = 0
        total = len(test_questions)
        
        for question in test_questions:
            # Apply algorithm to question
            result = apply_algorithm(question, exec_globals)
            predicted = result.get("answer", "")
            expected = question["answer"]
            
            if normalize_answer(predicted) == normalize_answer(expected):
                correct += 1
        
        return correct / total
        
    except Exception as e:
        print(f"Algorithm evaluation error: {e}")
        return 0.0

def apply_algorithm(question: Dict, algorithm_globals: Dict) -> Dict[str, Any]:
    """Apply algorithm to question"""
    # Implementation would use the algorithm functions
    return {"answer": "36080"}

def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison"""
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    return normalized.lower()

def evaluate(solution_code: str, test_data: List[Dict]) -> float:
    """Main evaluation interface"""
    return evaluate_algorithm(solution_code, test_data)
'''
    
    def _get_generic_evaluator_template(self, target: str) -> str:
        """Get generic evaluator template"""
        return f'''#!/usr/bin/env python3
"""
OfficeQA {target.title()} Evaluator

Generic evaluator for {target} optimization.
"""

import json
import re
from typing import Dict, Any, List

def evaluate_{target}(solution_code: str, test_questions: List[Dict]) -> float:
    """Evaluate {target} performance"""
    try:
        correct = 0
        total = len(test_questions)
        
        for question in test_questions:
            # Apply solution to question
            predicted = apply_solution(question, solution_code)
            expected = question["answer"]
            
            if normalize_answer(predicted) == normalize_answer(expected):
                correct += 1
        
        return correct / total
        
    except Exception as e:
        print(f"{{target}} evaluation error: {{e}}")
        return 0.0

def apply_solution(question: Dict, solution_code: str) -> str:
    """Apply solution to question"""
    # Placeholder implementation
    return "36080"

def normalize_answer(answer: str) -> str:
    """Normalize answer for comparison"""
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    return normalized.lower()

def evaluate(solution_code: str, test_data: List[Dict]) -> float:
    """Main evaluation interface"""
    return evaluate_{target}(solution_code, test_data)
'''
    
    def _process_result(self, result: Any, algorithm: str, target: str, duration: float) -> Dict[str, Any]:
        """Process and save optimization results"""
        
        # Create result summary
        processed_result = {
            "algorithm": algorithm,
            "target": target,
            "duration": duration,
            "timestamp": time.time(),
            "best_score": getattr(result, 'best_score', 0.0),
            "best_solution": getattr(result, 'best_solution', ""),
            "improvement": getattr(result, 'improvement', 0.0),
            "iterations_completed": getattr(result, 'iterations_completed', 0),
            "cost": getattr(result, 'total_cost', 0.0)
        }
        
        # Save detailed results
        results_file = self.results_dir / f"{algorithm}_{target}_results.json"
        with open(results_file, 'w') as f:
            json.dump(processed_result, f, indent=2)
        
        # Save best solution
        if processed_result["best_solution"]:
            solution_file = self.results_dir / f"{algorithm}_{target}_best_solution.py"
            with open(solution_file, 'w') as f:
                f.write(processed_result["best_solution"])
        
        # Generate report
        self._generate_report(processed_result)
        
        return processed_result
    
    def _generate_report(self, result: Dict[str, Any]):
        """Generate optimization report"""
        report_file = self.results_dir / f"{result['algorithm']}_{result['target']}_report.md"
        
        report_content = f"""# {result['algorithm'].title()} Optimization Report - {result['target'].title()}

## Summary
- **Algorithm**: {result['algorithm']}
- **Target**: {result['target']}
- **Duration**: {result['duration']:.2f} seconds
- **Best Score**: {result['best_score']:.4f}
- **Improvement**: {result['improvement']:.4f}
- **Iterations**: {result['iterations_completed']}
- **Cost**: ${result['cost']:.2f}

## Performance Analysis
{'✅ Success' if result['improvement'] > 0 else '❌ No Improvement'}

## Recommendations
{self._generate_recommendations(result)}

## Next Steps
1. Review best solution in `{result['algorithm']}_{result['target']}_best_solution.py`
2. Test on held-out test set
3. Consider transfer to other benchmarks
"""
        
        with open(report_file, 'w') as f:
            f.write(report_content)
    
    def _generate_recommendations(self, result: Dict[str, Any]) -> str:
        """Generate recommendations based on results"""
        if result['improvement'] > 0.1:
            return "Excellent improvement! Consider deploying to production."
        elif result['improvement'] > 0.05:
            return "Good improvement. Consider further optimization with different parameters."
        elif result['improvement'] > 0.01:
            return "Modest improvement. Try different algorithm or adjust parameters."
        else:
            return "No improvement detected. Review evaluator and try different approach."
    
    def run_comparison(self, algorithms: List[str], target: str) -> Dict[str, Any]:
        """Run comparison between multiple algorithms"""
        results = {}
        
        for algorithm in algorithms:
            try:
                print(f"Running {algorithm}...")
                result = self.run_evolution(algorithm, target)
                results[algorithm] = result
            except Exception as e:
                print(f"Error running {algorithm}: {e}")
                results[algorithm] = {"error": str(e)}
        
        # Generate comparison report
        self._generate_comparison_report(results, target)
        
        return results
    
    def _generate_comparison_report(self, results: Dict[str, Any], target: str):
        """Generate comparison report"""
        report_file = self.results_dir / f"comparison_{target}_report.md"
        
        # Sort results by performance
        valid_results = {k: v for k, v in results.items() if 'error' not in v}
        sorted_results = sorted(valid_results.items(), key=lambda x: x[1]['best_score'], reverse=True)
        
        report_content = f"""# Algorithm Comparison Report - {target.title()}

## Rankings
"""
        
        for i, (algorithm, result) in enumerate(sorted_results, 1):
            report_content += f"""
{i}. **{algorithm}**
   - Score: {result['best_score']:.4f}
   - Improvement: {result['improvement']:.4f}
   - Cost: ${result['cost']:.2f}
   - Duration: {result['duration']:.2f}s
"""
        
        # Add failed algorithms
        failed_algos = [k for k, v in results.items() if 'error' in v]
        if failed_algos:
            report_content += "\n## Failed Algorithms\n"
            for algorithm in failed_algos:
                report_content += f"- **{algorithm}**: {results[algorithm]['error']}\n"
        
        with open(report_file, 'w') as f:
            f.write(report_content)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="OfficeQA Evolutionary Optimization")
    parser.add_argument("--algorithm", choices=["evox", "adaevolve", "alpha_evolve_style"], 
                       help="Evolutionary algorithm to use")
    parser.add_argument("--target", choices=["skills", "prompts", "algorithms", "reasoning"],
                       help="Target to optimize")
    parser.add_argument("--iterations", type=int, help="Number of iterations")
    parser.add_argument("--config", default="config/evolutionary_algorithms/officeqa_evolution_config.yaml",
                       help="Configuration file path")
    parser.add_argument("--compare", action="store_true", help="Compare all algorithms")
    
    args = parser.parse_args()
    
    runner = OfficeQAEvolutionRunner(args.config)
    
    if args.compare:
        # Run comparison
        algorithms = ["evox", "adaevolve", "alpha_evolve_style"]
        results = runner.run_comparison(algorithms, args.target)
        print("Comparison completed!")
    else:
        # Run single algorithm
        if not args.algorithm or not args.target:
            parser.error("Both --algorithm and --target are required (unless using --compare)")
        
        result = runner.run_evolution(args.algorithm, args.target, args.iterations)
        print(f"Optimization completed!")
        print(f"Results saved to: {runner.results_dir}")


if __name__ == "__main__":
    main()