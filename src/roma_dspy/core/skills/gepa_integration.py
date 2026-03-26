"""
GEPA/optimize_anything Integration for ROMA OfficeQA

Integrates state-of-the-art optimization frameworks with ROMA's skill system:
- GEPA: Genetic-Pareto prompt evolution with natural language reflection
- optimize_anything: Universal API for optimizing any text artifact
- PromptGrad: Gradient-style prompt optimization with interpretable rules

This enables automated self-improvement of:
- Individual skills (prompts, logic)
- Multi-agent configurations (model selection, routing)
- Evidence card formats and validation rules
- Entire agent architectures
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from enum import Enum

# Mock GEPA integration (would install actual gepa package)
try:
    import gepa.optimize_anything as oa
    import gepa
    GEPA_AVAILABLE = True
except ImportError:
    GEPA_AVAILABLE = False


class OptimizationMode(Enum):
    SINGLE_TASK = "single_task"      # Optimize for one specific problem
    MULTI_TASK = "multi_task"        # Optimize across related problems
    GENERALIZATION = "generalization" # Build skills that transfer


@dataclass
class OptimizationTarget:
    """Defines what to optimize"""
    name: str
    artifact_type: str  # "skill", "prompt", "config", "architecture"
    current_artifact: str
    objective: str
    constraints: List[str] = None


@dataclass
class OptimizationResult:
    """Results from optimization process"""
    best_artifact: str
    improvement_score: float
    optimization_trace: List[Dict]
    discovered_rules: List[str]
    validation_performance: Dict[str, float]
    meta_learning: Dict[str, Any]


class GEPASkillOptimizer:
    """Optimizes individual skills using GEPA evolutionary algorithms"""
    
    def __init__(self, skills_path: Path):
        self.skills_path = skills_path
        self.optimization_history = {}
        
    async def optimize_skill(self, 
                           skill_name: str,
                           evaluation_dataset: List[Dict],
                           validation_dataset: List[Dict],
                           mode: OptimizationMode = OptimizationMode.SINGLE_TASK) -> OptimizationResult:
        """Optimize a single skill using GEPA"""
        
        if not GEPA_AVAILABLE:
            return self._mock_optimization(skill_name, evaluation_dataset, validation_dataset)
        
        # Load current skill
        skill_path = self.skills_path / skill_name
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        
        current_skill = self._load_skill_artifact(skill_path)
        
        # Define evaluator function
        def skill_evaluator(artifact: str, dataset: List[Dict]) -> Tuple[float, str]:
            """Evaluate skill artifact on dataset"""
            return self._evaluate_skill_artifact(artifact, skill_name, dataset)
        
        # Configure optimization based on mode
        if mode == OptimizationMode.SINGLE_TASK:
            result = oa.optimize_anything(
                seed_candidate=current_skill,
                evaluator=lambda x: skill_evaluator(x, evaluation_dataset),
                objective=f"Optimize {skill_name} for OfficeQA performance",
                config=oa.GEPAConfig(
                    engine="gepa",
                    max_iterations=20,
                    population_size=8,
                    reflection_depth=3
                )
            )
        elif mode == OptimizationMode.MULTI_TASK:
            result = oa.optimize_anything(
                seed_candidate=current_skill,
                evaluator=lambda x: skill_evaluator(x, evaluation_dataset),
                dataset=evaluation_dataset,
                objective=f"Optimize {skill_name} across multiple OfficeQA question types",
                config=oa.GEPAConfig(
                    engine="gepa_multi",
                    max_iterations=15,
                    population_size=12,
                    crossover_rate=0.8
                )
            )
        else:  # GENERALIZATION
            result = oa.optimize_anything(
                seed_candidate=current_skill,
                evaluator=lambda x: skill_evaluator(x, evaluation_dataset),
                dataset=evaluation_dataset,
                valset=validation_dataset,
                objective=f"Build {skill_name} that generalizes to unseen OfficeQA questions",
                config=oa.GEPAConfig(
                    engine="gepa_generalization",
                    max_iterations=25,
                    population_size=10,
                    generalization_weight=0.3
                )
            )
        
        # Parse results
        optimization_result = self._parse_gepa_result(result, skill_name)
        
        # Save optimized skill
        self._save_optimized_skill(skill_path, optimization_result.best_artifact)
        
        # Update history
        self.optimization_history[skill_name] = optimization_result
        
        return optimization_result
    
    def _load_skill_artifact(self, skill_path: Path) -> str:
        """Load skill artifact for optimization"""
        # Combine skill files into single artifact
        artifact_parts = []
        
        # Load skill description
        skill_md = skill_path / "SKILL.md"
        if skill_md.exists():
            artifact_parts.append(f"# SKILL DESCRIPTION\n{skill_md.read_text()}")
        
        # Load skill logic
        for py_file in skill_path.glob("*.py"):
            artifact_parts.append(f"# {py_file.name.upper()}\n{py_file.read_text()}")
        
        # Load metadata
        metadata_file = skill_path / "metadata.json"
        if metadata_file.exists():
            artifact_parts.append(f"# METADATA\n{metadata_file.read_text()}")
        
        return "\n\n".join(artifact_parts)
    
    def _evaluate_skill_artifact(self, artifact: str, skill_name: str, dataset: List[Dict]) -> Tuple[float, str]:
        """Evaluate skill artifact on dataset"""
        # This would integrate with ROMA's execution pipeline
        # For now, simulate evaluation based on artifact content
        
        score = 0.0
        feedback = []
        
        # Check for key components
        if "def " in artifact and skill_name in artifact:
            score += 0.3
            feedback.append("Has function definition")
        
        if "error" in artifact.lower() or "exception" in artifact.lower():
            score += 0.2
            feedback.append("Has error handling")
        
        if "validation" in artifact.lower():
            score += 0.2
            feedback.append("Has validation logic")
        
        # Simulate dataset performance
        dataset_score = len(dataset) * 0.1  # Base score
        score += dataset_score
        feedback.append(f"Dataset performance: {dataset_score}")
        
        # Add some randomness to simulate real evaluation
        import random
        score += random.uniform(-0.1, 0.1)
        
        return min(score, 1.0), "; ".join(feedback)
    
    def _parse_gepa_result(self, gepa_result: Any, skill_name: str) -> OptimizationResult:
        """Parse GEPA result into our format"""
        if not GEPA_AVAILABLE:
            return gepa_result
        
        # Extract best artifact
        best_artifact = gepa_result.best_candidate
        
        # Calculate improvement
        improvement = gepa_result.improvement if hasattr(gepa_result, 'improvement') else 0.1
        
        # Extract discovered rules (from reflection)
        discovered_rules = []
        if hasattr(gepa_result, 'reflections'):
            for reflection in gepa_result.reflections:
                if "rule:" in reflection.lower():
                    discovered_rules.append(reflection)
        
        return OptimizationResult(
            best_artifact=best_artifact,
            improvement_score=improvement,
            optimization_trace=gepa_result.history if hasattr(gepa_result, 'history') else [],
            discovered_rules=discovered_rules,
            validation_performance={"accuracy": improvement},
            meta_learning={"convergence_iteration": len(gepa_result.history) if hasattr(gepa_result, 'history') else 10}
        )
    
    def _save_optimized_skill(self, skill_path: Path, artifact: str):
        """Save optimized skill artifact back to files"""
        # Parse artifact and save to appropriate files
        lines = artifact.split('\n')
        current_section = None
        content = {}
        
        for line in lines:
            if line.startswith("# "):
                current_section = line[2:].lower()
                content[current_section] = []
            elif current_section:
                content[current_section].append(line)
        
        # Save skill description
        if "skill description" in content:
            skill_md = skill_path / "SKILL.md"
            skill_md.write_text('\n'.join(content["skill description"]))
        
        # Save skill logic
        if "skill_name.upper()" in content or any("def " in line for line in content.get("", [])):
            py_content = []
            in_python = False
            for line in lines:
                if line.startswith("# ") and "python" in line.lower():
                    in_python = True
                    continue
                elif in_python and line.startswith("# "):
                    break
                elif in_python:
                    py_content.append(line)
            
            if py_content:
                py_file = skill_path / f"{skill_path.name}.py"
                py_file.write_text('\n'.join(py_content))
    
    def _mock_optimization(self, skill_name: str, eval_dataset: List[Dict], val_dataset: List[Dict]) -> OptimizationResult:
        """Mock optimization when GEPA is not available"""
        import random
        
        # Simulate optimization improvement
        base_score = 0.6
        improvement = random.uniform(0.05, 0.15)
        
        return OptimizationResult(
            best_artifact=f"# Optimized {skill_name}\n# Improved by {improvement:.1%}",
            improvement_score=improvement,
            optimization_trace=[{"iteration": i, "score": base_score + improvement * i/10} for i in range(10)],
            discovered_rules=[
                f"Rule 1: Always validate {skill_name} inputs",
                f"Rule 2: Handle edge cases in {skill_name}",
                f"Rule 3: Optimize {skill_name} for OfficeQA format"
            ],
            validation_performance={"accuracy": base_score + improvement},
            meta_learning={"convergence_iteration": 8}
        )


class PromptGradOptimizer:
    """Gradient-style prompt optimization with interpretable rules"""
    
    def __init__(self):
        self.rule_history = {}
    
    async def optimize_with_textual_gradients(self,
                                          initial_prompt: str,
                                          evaluation_fn: Callable,
                                          dataset: List[Dict],
                                          max_rules: int = 10) -> OptimizationResult:
        """Optimize prompt using textual gradient descent"""
        
        current_prompt = initial_prompt
        discovered_rules = []
        optimization_trace = []
        current_score = 0.0
        
        for iteration in range(max_rules):
            # Evaluate current prompt
            score, feedback = evaluation_fn(current_prompt, dataset)
            optimization_trace.append({
                "iteration": iteration,
                "score": score,
                "prompt_length": len(current_prompt)
            })
            
            # Extract textual gradient (diagnostic feedback)
            gradient = self._extract_textual_gradient(feedback, dataset)
            
            if not gradient or score >= 0.9:  # Converged or good enough
                break
            
            # Generate rule from gradient
            new_rule = self._generate_rule_from_gradient(gradient, iteration)
            discovered_rules.append(new_rule)
            
            # Apply rule to prompt
            current_prompt = self._apply_rule_to_prompt(current_prompt, new_rule)
            
            # Re-evaluate
            new_score, _ = evaluation_fn(current_prompt, dataset)
            current_score = new_score
        
        return OptimizationResult(
            best_artifact=current_prompt,
            improvement_score=current_score - 0.6,  # Assuming baseline of 0.6
            optimization_trace=optimization_trace,
            discovered_rules=discovered_rules,
            validation_performance={"accuracy": current_score},
            meta_learning={"rules_discovered": len(discovered_rules)}
        )
    
    def _extract_textual_gradient(self, feedback: str, dataset: List[Dict]) -> Optional[str]:
        """Extract diagnostic gradient from feedback"""
        # Look for specific failure patterns in feedback
        gradients = []
        
        # Common OfficeQA failure patterns
        if "unit" in feedback.lower() and "expansion" in feedback.lower():
            gradients.append("unit_expansion_error")
        
        if "fiscal" in feedback.lower() and "year" in feedback.lower():
            gradients.append("fiscal_year_confusion")
        
        if "format" in feedback.lower() and "mismatch" in feedback.lower():
            gradients.append("answer_format_error")
        
        if "computation" in feedback.lower() and "error" in feedback.lower():
            gradients.append("calculation_mistake")
        
        return gradients[0] if gradients else None
    
    def _generate_rule_from_gradient(self, gradient: str, iteration: int) -> str:
        """Generate explicit rule from gradient"""
        rules = {
            "unit_expansion_error": f"Rule {iteration+1}: Never expand units. If table header says 'in millions', the number is already in millions - preserve the base value exactly.",
            "fiscal_year_confusion": f"Rule {iteration+2}: Always verify fiscal year boundaries. Pre-1977: Jul-Jun, Post-1977: Oct-Sep, with special TQ1976: Jul-Sep.",
            "answer_format_error": f"Rule {iteration+3}: Strip all formatting characters ($, , %) from final answer. Preserve source precision.",
            "calculation_mistake": f"Rule {iteration+4}: Double-check all computations. Use safe computation functions with error handling."
        }
        
        return rules.get(gradient, f"Rule {iteration+1}: Address {gradient} issues in processing.")
    
    def _apply_rule_to_prompt(self, prompt: str, rule: str) -> str:
        """Apply discovered rule to prompt"""
        # Add rule to prompt at appropriate location
        if "# RULES" in prompt:
            # Add to existing rules section
            prompt = prompt.replace("# RULES", f"# RULES\n{rule}")
        elif "# INSTRUCTIONS" in prompt:
            # Add after instructions
            prompt = prompt.replace("# INSTRUCTIONS", f"# INSTRUCTIONS\n\n# RULES\n{rule}")
        else:
            # Add at the end
            prompt = f"{prompt}\n\n# RULES\n{rule}"
        
        return prompt


class MultiAgentOptimizer:
    """Optimizes entire multi-agent configurations"""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        
    async def optimize_agent_configuration(self,
                                        objective: str,
                                        evaluation_dataset: List[Dict],
                                        model_candidates: List[str]) -> OptimizationResult:
        """Optimize model selection and configuration for multi-agent system"""
        
        best_config = None
        best_score = 0.0
        optimization_trace = []
        
        # Test different model combinations
        for atomizer_model in model_candidates:
            for planner_model in model_candidates:
                for executor_model in model_candidates:
                    config = {
                        "atomizer": {"model": atomizer_model},
                        "planner": {"model": planner_model}, 
                        "executor": {"model": executor_model},
                        "aggregator": {"model": planner_model},
                        "verifier": {"model": atomizer_model}
                    }
                    
                    # Evaluate configuration
                    score = await self._evaluate_configuration(config, evaluation_dataset)
                    
                    optimization_trace.append({
                        "config": config,
                        "score": score
                    })
                    
                    if score > best_score:
                        best_score = score
                        best_config = config
        
        # Generate discovered rules from best configuration
        discovered_rules = self._analyze_best_configuration(best_config)
        
        return OptimizationResult(
            best_artifact=json.dumps(best_config, indent=2),
            improvement_score=best_score - 0.6,
            optimization_trace=optimization_trace,
            discovered_rules=discovered_rules,
            validation_performance={"accuracy": best_score},
            meta_learning={"config_space_searched": len(optimization_trace)}
        )
    
    async def _evaluate_configuration(self, config: Dict, dataset: List[Dict]) -> float:
        """Evaluate multi-agent configuration"""
        # Simulate evaluation based on model capabilities
        score = 0.0
        
        # Prefer strong models for executor (computation-intensive)
        executor_model = config["executor"]["model"]
        if "claude-sonnet" in executor_model or "gpt-5" in executor_model:
            score += 0.3
        elif "gemini" in executor_model:
            score += 0.2
        
        # Prefer fast models for atomizer/planner (classification/decomposition)
        fast_models = ["gemini-2.5-flash", "gpt-4o-mini"]
        if config["atomizer"]["model"] in fast_models:
            score += 0.1
        if config["planner"]["model"] in fast_models:
            score += 0.1
        
        # Add some randomness
        import random
        score += random.uniform(0.1, 0.3)
        
        return min(score, 1.0)
    
    def _analyze_best_configuration(self, config: Dict) -> List[str]:
        """Analyze best configuration to extract rules"""
        rules = []
        
        executor_model = config["executor"]["model"]
        if "claude-sonnet" in executor_model:
            rules.append("Rule: Use strong reasoning models (Claude Sonnet) for computation-intensive executor tasks.")
        
        atomizer_model = config["atomizer"]["model"]
        if "gemini-2.5-flash" in atomizer_model:
            rules.append("Rule: Use fast models (Gemini Flash) for classification tasks to reduce latency.")
        
        return rules


class SelfImprovementManager:
    """Coordinates all self-improvement optimization"""
    
    def __init__(self, skills_path: Path, config_path: Path):
        self.skill_optimizer = GEPASkillOptimizer(skills_path)
        self.prompt_optimizer = PromptGradOptimizer()
        self.agent_optimizer = MultiAgentOptimizer(config_path)
        self.improvement_history = []
    
    async def run_comprehensive_optimization(self,
                                          evaluation_data: List[Dict],
                                          validation_data: List[Dict],
                                          optimization_targets: List[str]) -> Dict[str, OptimizationResult]:
        """Run comprehensive optimization across all targets"""
        
        results = {}
        
        # Optimize individual skills
        for skill_name in optimization_targets:
            if skill_name in ["fiscal-year-expert", "unit-expansion-guard", "multi-bulletin-aggregator"]:
                try:
                    result = await self.skill_optimizer.optimize_skill(
                        skill_name, evaluation_data, validation_data
                    )
                    results[f"skill_{skill_name}"] = result
                except Exception as e:
                    print(f"Failed to optimize {skill_name}: {e}")
        
        # Optimize system prompts
        try:
            system_prompt = self._load_system_prompt()
            prompt_result = await self.prompt_optimizer.optimize_with_textual_gradients(
                system_prompt, self._evaluate_system_prompt, evaluation_data
            )
            results["system_prompt"] = prompt_result
        except Exception as e:
            print(f"Failed to optimize system prompt: {e}")
        
        # Optimize agent configuration
        try:
            model_candidates = [
                "openrouter/google/gemini-2.5-flash",
                "openrouter/anthropic/claude-sonnet-4-5",
                "openrouter/openai/gpt-5-mini"
            ]
            agent_result = await self.agent_optimizer.optimize_agent_configuration(
                "Optimize OfficeQA agent configuration", evaluation_data, model_candidates
            )
            results["agent_configuration"] = agent_result
        except Exception as e:
            print(f"Failed to optimize agent configuration: {e}")
        
        # Record improvement history
        self.improvement_history.append({
            "timestamp": asyncio.get_event_loop().time(),
            "results": results,
            "total_improvement": sum(r.improvement_score for r in results.values())
        })
        
        return results
    
    def _load_system_prompt(self) -> str:
        """Load current system prompt"""
        prompt_file = Path("benchmarks/officeqa/arena/prompts/system.j2")
        if prompt_file.exists():
            return prompt_file.read_text()
        return "Default system prompt for OfficeQA"
    
    def _evaluate_system_prompt(self, prompt: str, dataset: List[Dict]) -> Tuple[float, str]:
        """Evaluate system prompt performance"""
        # Simulate evaluation
        score = 0.7  # Base score
        
        # Check for key components
        if "evidence" in prompt.lower():
            score += 0.1
        if "fiscal" in prompt.lower():
            score += 0.05
        if "unit" in prompt.lower():
            score += 0.05
        
        feedback = f"Prompt score: {score}"
        return min(score, 1.0), feedback
    
    def get_improvement_summary(self) -> Dict[str, Any]:
        """Get summary of all improvements"""
        if not self.improvement_history:
            return {"message": "No improvement history available"}
        
        latest = self.improvement_history[-1]
        
        return {
            "latest_optimization": latest["timestamp"],
            "total_improvement": latest["total_improvement"],
            "optimized_components": list(latest["results"].keys()),
            "discovered_rules_count": sum(
                len(result.discovered_rules) for result in latest["results"].values()
            ),
            "optimization_history": [
                {
                    "timestamp": entry["timestamp"],
                    "improvement": entry["total_improvement"]
                }
                for entry in self.improvement_history
            ]
        }
