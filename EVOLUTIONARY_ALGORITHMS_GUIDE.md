# Evolutionary Algorithms for OfficeQA and AI Benchmarks

## 🧬 Executive Summary

This guide documents the state-of-the-art evolutionary algorithms for AI optimization, focusing on Berkeley Sky Computing Labs' **SkyDiscover** framework, **EvoX** and **AdaEvolve**, and Google DeepMind's **AlphaEvolve**. We provide specific configurations and strategies for applying these systems to OfficeQA and other benchmarks.

---

## 🏢 Berkeley Sky Computing Labs - SkyDiscover Framework

### Overview
**SkyDiscover** is a modular, flexible framework for AI-driven scientific and algorithmic discovery that enables rapid implementation and comparison of evolutionary algorithms.

### Key Innovations
- **Modular Architecture**: Decomposes evolutionary loops into reusable components
- **Plug-and-Play Interface**: Simple API for different search algorithms
- **Built-in Algorithms**: EvoX, AdaEvolve, plus support for GEPA, OpenEvolve, ShinkaEvolve
- **200+ Task Validation**: Extensively tested across mathematical optimization, systems design, and programming

### Performance Highlights
- 🏆 **Best open-source performance** on Frontier-CS: +34% median improvement over baselines
- 💪 **Matches/exceeds AlphaEvolve** on 6/8 math benchmarks and 6/6 systems optimization tasks
- 🚀 **Real-world impact**: 41% lower cloud transfer costs, 14% better GPU load balance, 29% lower KV-cache pressure

---

## 🧬 EvoX: Meta-Evolution for Automated Discovery

### Core Concept
**EvoX** treats the evolution strategy itself as an evolvable object, using two coupled loops:
1. **Solution Evolution**: Generate and evaluate candidate solutions
2. **Strategy Evolution**: Adapt how new candidates are generated

### Technical Architecture
```
┌─────────────────┐    ┌─────────────────┐
│  Solution Loop  │◄──►│  Strategy Loop  │
│                 │    │                 │
│ • Generate      │    │ • Adapt         │
│ • Evaluate      │    │ • Optimize      │
│ • Select        │    │ • Evolve        │
└─────────────────┘    └─────────────────┘
```

### Key Features
- **Dynamic Strategy Evolution**: LLMs evolve their own optimization process
- **Adaptive Exploration**: Breaks through stagnation points automatically
- **Meta-Learning**: Treats evolution as a learning problem
- **Cost Efficiency**: <$5 compute on tasks where others spend 3x more and stagnate

### Performance Comparison
| Algorithm | Math Benchmarks | Systems Tasks | Frontier-CS | Cost Efficiency |
|------------|----------------|---------------|-------------|----------------|
| **EvoX** | 6/8 SOTA | 7/7 SOTA | **75.5 median** | **High** |
| AlphaEvolve | Human SOTA | Human SOTA | 56.2 | Medium |
| GEPA | 4/8 | 5/7 | Baseline | Medium |
| OpenEvolve | 3/8 | 4/7 | Baseline | Low |

### Usage for OfficeQA
```python
from skydiscover import run_discovery

# EvoX configuration for OfficeQA skill optimization
result = run_discovery(
    evaluator="officeqa_skill_evaluator.py",
    search="evox",  # Meta-evolution
    model="gpt-5",
    iterations=100,
    budget=50.0  # Cost limit in dollars
)
```

---

## 🎯 AdaEvolve: Adaptive Zeroth-Order Optimization

### Core Concept
**AdaEvolve** uses fitness improvement trajectories as gradient analogues for zeroth-order optimization, with hierarchical adaptivity across three levels:
1. **Local**: Dynamic exploration intensity within subpopulations
2. **Global**: Resource allocation across populations (islands)
3. **Meta**: Strategy generation from unified improvement signal

### Technical Architecture
```
Improvement Signal
       ↓
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Local Level   │    │  Global Level   │    │   Meta Level    │
│                 │    │                 │    │                 │
│ • Exploration   │    │ • Resource      │    │ • Strategy      │
│ • Intensity     │    │ • Allocation    │    │ • Generation    │
│ • Within Islands│    │ • Cross Islands │    │ • Guidance      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Features
- **Gradient Analogue**: Uses improvement trajectories instead of numerical gradients
- **Hierarchical Adaptation**: Three synchronized adaptation levels
- **Resource Efficiency**: Smart compute allocation across populations
- **Stagnation Prevention**: Automatically adjusts when progress stalls

### Performance Highlights
- **34% median improvement** over strongest open-source baselines on Frontier-CS
- **3× mean improvement** on programming tasks
- **Cost-effective**: Breaks plateaus where other frameworks stagnate

### Usage for OfficeQA
```python
# AdaEvolve for OfficeQA prompt optimization
result = run_discovery(
    evaluator="officeqa_prompt_evaluator.py",
    search="adaevolve",  # Adaptive optimization
    model="gpt-5",
    iterations=100,
    population_size=50,
    islands=5
)
```

---

## 🚀 AlphaEvolve: Google DeepMind's Evolutionary Coding Agent

### Core Concept
**AlphaEvolve** orchestrates an autonomous pipeline of LLMs to improve algorithms through direct code modifications, using evolutionary search with automated evaluators.

### Technical Architecture
```
Initial Code → LLM Mutations → Evaluation → Selection → Improvement
     ↑                                                    ↓
     └─────────────── Evolution Loop ←─────────────────────┘
```

### Key Achievements
- **56-year mathematical breakthrough**: 4x4 complex matrix multiplication with 48 multiplications (vs Strassen's 49)
- **Real-world optimizations**: 0.7% Google data center efficiency, 23% Gemini kernel speedup
- **Broad applicability**: 50+ mathematical problems, infrastructure optimization, AI training acceleration

### Evolution Strategy
1. **Code Generation**: Gemini 2.0 Flash/Pro suggest targeted modifications
2. **Automated Evaluation**: Verifiers ensure functional correctness
3. **Database Storage**: High-scoring programs stored as genetic material
4. **Evolutionary Selection**: Genetic algorithm selects promising variants
5. **Iterative Improvement**: Loop continues until convergence

### Usage Patterns
```python
# AlphaEvolve-style evolutionary loop (conceptual)
def alpha_evolve_optimization(initial_code, evaluator, iterations=100):
    population = [initial_code]
    database = PopulationDatabase()
    
    for iteration in range(iterations):
        # Select high-scoring programs
        candidates = database.select_top_k(k=10)
        
        # Generate mutations using LLM
        for candidate in candidates:
            mutations = llm_generate_mutations(candidate, candidates)
            
            # Evaluate mutations
            for mutation in mutations:
                score = evaluator.evaluate(mutation)
                database.add(mutation, score)
    
    return database.get_best()
```

---

## 🎯 OfficeQA-Specific Evolutionary Strategies

### Problem Characteristics
- **Grounded Reasoning**: Multi-document synthesis from Treasury Bulletins
- **Error Patterns**: Unit expansion (15-20%), fiscal year confusion (8-12%), etc.
- **Evaluation**: Exact-match scoring with strict formatting requirements
- **Domain**: Financial documents spanning 1939-2025 (89,000 pages, 26M+ values)

### Evolutionary Algorithm Selection

#### 1. **EvoX for Skill Discovery**
**Best for**: Discovering entirely new skill architectures
```python
# EvoX configuration for OfficeQA skill meta-evolution
evox_config = {
    "search": "evox",
    "model": "gpt-5",
    "iterations": 100,
    "meta_evolution": {
        "strategy_population": 20,
        "solution_population": 50,
        "adaptation_frequency": 10
    },
    "officeqa_specific": {
        "error_patterns": ["unit_expansion", "fiscal_year", "multi_bulletin"],
        "validation_set": "officeqa_validation.json",
        "scoring_function": "exact_match_with_formatting"
    }
}
```

#### 2. **AdaEvolve for Prompt Optimization**
**Best for**: Improving existing prompts and skills
```python
# AdaEvolve for OfficeQA prompt refinement
adaevolve_config = {
    "search": "adaevolve",
    "model": "gpt-5",
    "iterations": 100,
    "hierarchical_adaptation": {
        "local_exploration": "dynamic",
        "global_allocation": "adaptive",
        "meta_strategy": "improvement_driven"
    },
    "officeqa_specific": {
        "prompt_components": ["system_prompt", "few_shot_examples", "instructions"],
        "adaptation_triggers": ["accuracy_plateau", "error_pattern_increase"],
        "evaluation_frequency": 5
    }
}
```

#### 3. **AlphaEvolve-Style for Algorithm Discovery**
**Best for**: Finding new computational approaches
```python
# AlphaEvolve-style for OfficeQA algorithm discovery
alpha_evolve_config = {
    "search": "alpha_evolve_style",
    "model": "gpt-5",
    "iterations": 100,
    "evolution_parameters": {
        "mutation_rate": 0.1,
        "crossover_rate": 0.7,
        "selection_pressure": "elitist",
        "population_size": 100
    },
    "officeqa_specific": {
        "algorithm_space": ["fiscal_year_calculation", "unit_conversion", "time_series_aggregation"],
        "verification": "mathematical_proof + empirical_testing",
        "optimization_objectives": ["accuracy", "efficiency", "generalizability"]
    }
}
```

### Targeted Evolution for Specific Error Patterns

#### Unit Expansion Prevention
```python
def unit_expansion_evolution():
    """Evolve unit expansion detection and prevention"""
    return {
        "mutation_operators": [
            "add_unit_validation_rules",
            "modify_number_formatting_logic", 
            "enhance_digit_count_analysis"
        ],
        "fitness_function": "unit_expansion_error_rate",
        "constraints": ["preserve_base_numbers", "maintain_format_compliance"]
    }
```

#### Fiscal Year Disambiguation
```python
def fiscal_year_evolution():
    """Evolve fiscal year boundary handling"""
    return {
        "mutation_operators": [
            "refine_boundary_detection",
            "improve_transition_quarter_handling",
            "enhance_date_range_validation"
        ],
        "fitness_function": "fiscal_year_accuracy",
        "constraints": ["handle_pre_1977", "handle_post_1977", "handle_tq1976"]
    }
```

#### Multi-Bulletin Aggregation
```python
def multi_bulletin_evolution():
    """Evolve time series aggregation strategies"""
    return {
        "mutation_operators": [
            "optimize_aggregation_algorithms",
            "improve_revision_handling",
            "enhance_gap_detection"
        ],
        "fitness_function": "multi_bulletin_accuracy",
        "constraints": ["handle_missing_data", "detect_revisions", "maintain_consistency"]
    }
```

---

## 📊 Benchmark-Specific Configurations

### OfficeQA Challenge
```python
officeqa_config = {
    "framework": "skydiscover",
    "search_algorithms": ["evox", "adaevolve"],
    "models": ["gpt-5", "gemini-3.0-pro"],
    "iterations": 100,
    "budget": 100.0,  # $100 budget
    "evaluation": {
        "metric": "exact_match_accuracy",
        "validation_split": 0.2,
        "test_split": 0.3
    },
    "optimization_targets": [
        "skill_architectures",
        "prompt_templates", 
        "reasoning_chains",
        "error_correction_rules"
    ]
}
```

### SealQA (Search-Augmented QA)
```python
sealqa_config = {
    "framework": "skydiscover",
    "search": "evox",  # Best for transfer learning
    "models": ["gpt-5"],
    "iterations": 150,
    "specialization": {
        "search_augmentation": True,
        "noise_robustness": True,
        "source_conflict_resolution": True
    },
    "transfer_targets": ["BrowseComp"]  # Proven 5.3% zero-shot transfer
}
```

### CORE-Bench (Scientific Reasoning)
```python
core_bench_config = {
    "framework": "skydiscover", 
    "search": "adaevolve",  # Best for complex optimization
    "models": ["gpt-5"],
    "iterations": 200,
    "specialization": {
        "scientific_computation": True,
        "experimental_reproduction": True,
        "code_execution": True
    }
}
```

### SWE-Bench (Software Engineering)
```python
swe_bench_config = {
    "framework": "skydiscover",
    "search": "alpha_evolve_style",  # Best for code optimization
    "models": ["gpt-5"],
    "iterations": 100,
    "specialization": {
        "code_reasoning": True,
        "debugging": True,
        "testing": True
    }
}
```

---

## 🛠️ Implementation Guide

### Installation
```bash
# Install SkyDiscover framework
pip install skydiscover

# Or install with uv for faster dependency resolution
uv add skydiscover
```

### Basic Usage
```python
from skydiscover import run_discovery

# Simple discovery run
result = run_discovery(
    evaluator="my_evaluator.py",
    search="evox",
    model="gpt-5",
    iterations=100
)

print(f"Best solution: {result.best_solution}")
print(f"Best score: {result.best_score}")
```

### Advanced Configuration
```python
# Custom evolutionary configuration
custom_config = {
    "search": "evox",
    "model": "gpt-5",
    "iterations": 100,
    "population_size": 50,
    "elitism_rate": 0.1,
    "mutation_rate": 0.2,
    "crossover_rate": 0.7,
    "adaptation_strategy": "meta_evolution",
    "budget": 100.0,
    "early_stopping": {
        "patience": 20,
        "min_improvement": 0.001
    }
}

result = run_discovery(
    evaluator="officeqa_evaluator.py",
    **custom_config
)
```

### Evaluator Template for OfficeQA
```python
# officeqa_evaluator.py
def evaluate_solution(solution_code, test_questions):
    """Evaluate OfficeQA solution"""
    try:
        # Load solution
        exec(solution_code, globals())
        
        correct = 0
        total = len(test_questions)
        
        for question in test_questions:
            predicted = solve_officeqa_question(question)
            expected = question["answer"]
            
            # OfficeQA scoring logic
            if normalize_answer(predicted) == normalize_answer(expected):
                correct += 1
        
        accuracy = correct / total
        return accuracy
        
    except Exception as e:
        return 0.0  # Penalize crashes

def normalize_answer(answer):
    """OfficeQA answer normalization"""
    import re
    normalized = str(answer).strip()
    normalized = re.sub(r'[$,%]', '', normalized)
    normalized = re.sub(r',', '', normalized)
    normalized = normalized.replace('–', '-').replace('—', '-')
    return normalized.lower()
```

---

## 📈 Performance Optimization Strategies

### 1. **Algorithm Selection Guidelines**
- **EvoX**: Novel problems, meta-optimization needed, high-budget scenarios
- **AdaEvolve**: Existing solutions to improve, cost-sensitive applications
- **AlphaEvolve-style**: Code optimization, algorithm discovery, mathematical problems

### 2. **Budget Management**
```python
budget_config = {
    "total_budget": 100.0,  # $100 total
    "iteration_budget": 1.0,  # $1 per iteration
    "early_stopping": True,
    "adaptive_budgeting": True,  # Reallocate based on progress
    "cost_monitoring": "real_time"
}
```

### 3. **Population Management**
```python
population_config = {
    "initial_size": 50,
    "max_size": 200,
    "elitism_rate": 0.1,
    "diversity_maintenance": True,
    "age_diversity": True,  # Maintain solution age diversity
    "novelty_search": True  # Include novel solutions
}
```

### 4. **Evaluation Optimization**
```python
evaluation_config = {
    "parallel_evaluation": True,
    "batch_size": 10,
    "caching": True,
    "early_termination": True,  # Stop evaluating obviously bad solutions
    "incremental_evaluation": True  # Quick evaluation first, detailed later
}
```

---

## 🔄 Integration with Existing Systems

### ROMA Integration
```python
# Integrate SkyDiscover with ROMA skill optimization
from skydiscover import run_discovery
from roma_dspy.core.skills import SkillOptimizer

class ROMAEvolutionaryOptimizer(SkillOptimizer):
    def __init__(self, framework="skydiscover"):
        self.framework = framework
    
    def optimize_skill_evolutionary(self, skill_name, target_benchmark):
        """Use evolutionary algorithms for skill optimization"""
        
        evaluator = f"{target_benchmark}_skill_evaluator.py"
        
        # Try EvoX first for meta-optimization
        evox_result = run_discovery(
            evaluator=evaluator,
            search="evox",
            model="gpt-5",
            iterations=50,
            budget=50.0
        )
        
        # Refine with AdaEvolve
        if evox_result.best_score < 0.8:
            ada_result = run_discovery(
                evaluator=evaluator,
                search="adaevolve", 
                model="gpt-5",
                iterations=50,
                initial_solution=evox_result.best_solution,
                budget=50.0
            )
            return ada_result
        
        return evox_result
```

### Arena Platform Integration
```python
# Arena submission with evolutionary optimization
def evolutionary_arena_submission():
    """Submit optimized solution to Arena"""
    
    # Optimize skills using evolutionary algorithms
    optimizer = ROMAEvolutionaryOptimizer()
    
    for skill in ["fiscal-year-expert", "unit-expansion-guard", "multi-bulletin-aggregator"]:
        result = optimizer.optimize_skill_evolutionary(skill, "officeqa")
        
        # Update skill with optimized version
        update_skill_with_result(skill, result.best_solution)
    
    # Submit to Arena
    submit_to_arena()
```

---

## 📊 Expected Performance Gains

### OfficeQA Projections
| Algorithm | Expected Improvement | Cost | Time to Convergence |
|-----------|-------------------|------|-------------------|
| **EvoX** | 12-15 points | $100 | 100 iterations |
| **AdaEvolve** | 8-12 points | $50 | 75 iterations |
| **AlphaEvolve-style** | 10-14 points | $75 | 80 iterations |

### Cross-Benchmark Transfer
| Source → Target | Transfer Gain | Confidence |
|----------------|---------------|------------|
| OfficeQA → CORE-Bench | 3-5 points | High |
| SealQA → BrowseComp | 5.3 points (proven) | Very High |
| OfficeQA → SWE-Bench | 2-4 points | Medium |

---

## 🎯 Best Practices & Recommendations

### 1. **Start Simple**
- Begin with AdaEvolve for existing skill improvement
- Progress to EvoX for novel skill discovery
- Use AlphaEvolve-style for algorithmic breakthroughs

### 2. **Budget Wisely**
- Allocate 70% budget to main optimization, 30% to exploration
- Use early stopping to avoid wasted iterations
- Monitor cost/performance ratio in real-time

### 3. **Validate Rigorously**
- Use held-out validation sets
- Test for overfitting to training data
- Verify generalization across question types

### 4. **Iterate and Refine**
- Start with broad search, then focus on promising areas
- Use insights from failed runs to improve evaluators
- Maintain diversity in solution populations

### 5. **Document Everything**
- Track evolution trajectories
- Record successful mutation patterns
- Maintain reproducibility with seed management

---

## 🔮 Future Directions

### Emerging Trends
- **Multi-Objective Evolution**: Optimize accuracy, cost, and speed simultaneously
- **Neuro-Evolution**: Evolve neural architectures alongside reasoning
- **Transfer Learning**: Cross-benchmark skill transfer optimization
- **Meta-Learning**: Learn how to learn across multiple benchmarks

### Research Opportunities
- **Automated Evaluator Generation**: Use LLMs to create evaluation functions
- **Hierarchical Evolution**: Evolve at multiple abstraction levels
- **Collaborative Evolution**: Multiple agents evolving together
- **Continuous Evolution**: Always-on optimization systems

---

## 📚 References & Resources

### Papers
- EvoX: Meta-Evolution for Automated Discovery (arXiv:2602.23413)
- AdaEvolve: Adaptive LLM-Driven Zeroth-Order Optimization (arXiv:2506.13131)
- AlphaEvolve: A coding agent for scientific and algorithmic discovery (arXiv:2506.13131)
- SkyDiscover: A Flexible Framework for AI-Driven Discovery (arXiv:2602.12670)

### Code & Frameworks
- **SkyDiscover**: https://github.com/skydiscover-ai/skydiscover
- **EvoX Documentation**: https://skydiscover-ai.github.io/blog-evox.html
- **AdaEvolve Guide**: https://skydiscover-ai.github.io/blog-adaevolve.html

### Tools & APIs
- SkyDiscover CLI: `skydiscover-run`
- Python API: `from skydiscover import run_discovery`
- Configuration: YAML and Python dictionary formats

---

## 🏆 Conclusion

Evolutionary algorithms represent the cutting edge of AI optimization, with Berkeley's SkyDiscover framework providing the most flexible and powerful platform for OfficeQA and other benchmarks. By leveraging EvoX's meta-evolution, AdaEvolve's adaptive optimization, and AlphaEvolve's proven track record, we can achieve significant performance improvements beyond traditional approaches.

The key is selecting the right algorithm for the right problem, managing budgets effectively, and maintaining rigorous validation throughout the optimization process. With these tools and strategies, OfficeQA performance can be substantially improved while building transferable capabilities for other benchmarks.

**Next Steps**: Implement SkyDiscover with EvoX for OfficeQA skill meta-evolution, validate on held-out sets, and prepare for Arena submission when CLI issues are resolved.