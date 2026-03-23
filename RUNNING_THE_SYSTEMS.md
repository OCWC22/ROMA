# Running the Complete Integration

## ✅ All Systems Installed

```bash
✓ DSPy installed (v3.0.4b1)
✓ GEPA installed (v0.0.17)
✓ RLM installed (v0.1.1)
⚠ SkyDiscover not installed - mock implementation available
```

## 🔑 Required: API Keys

Set these environment variables before running:

```bash
# OpenAI (for GPT models)
export OPENAI_API_KEY="sk-..."

# Anthropic (for Claude models - recommended for OfficeQA)
export ANTHROPIC_API_KEY="sk-ant-..."

# Google (for Gemini models - cheap/fast for atomizer/planner/aggregator roles)
export GOOGLE_API_KEY="..."
```

## 🚀 Run Commands

### Quick Test (Mock Mode - No API Keys Needed)
```bash
cd /Users/chen/Documents/GitHub/ROMA
uv run python scripts/run_complete_integration.py --mode test --questions 3
```

### With API Keys (Real DSPy/ROMA Execution)
```bash
# Set API keys first
export OPENAI_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"

# Run with real models
cd /Users/chen/Documents/GitHub/ROMA
uv run python scripts/run_complete_integration.py --mode test --questions 5
```

### Install SkyDiscover (Optional - for EvoX/AdaEvolve)
```bash
uv pip install skydiscover
```

## 📊 What Each System Does

| System | Status | What It Does |
|--------|--------|--------------|
| **ROMA** | ✅ Installed | DSPy recursive agent (task decomposition) |
| **GEPA+** | ✅ Installed | Evolutionary prompt optimization |
| **RLM** | ✅ Installed | REPL-based corpus traversal |
| **Auto-Benchmark** | ✅ Works | Generates tests from usage patterns |
| **EvoSkill** | ✅ Works | Auto-discovers skills from failures |
| **SkyDiscover** | ⚠️ Optional | EvoX/AdaEvolve meta-evolution |

## 🎯 Third Direction: Automated Evaluation

**Fully Implemented** in `src/roma_dspy/core/skills/automated_benchmark_generator.py`

This creates benchmarks completely automatically from usage patterns:
- Extracts test cases from execution traces
- Generates tool requirements
- Creates prompt specifications
- Zero human intervention

**Test it now:**
```python
from src.roma_dspy.core.skills.automated_benchmark_generator import create_benchmark_from_usage
import asyncio

async def test():
    traces = [{"question_id": "q1", "question": "test", "final_answer": "36080", "execution_steps": []}]
    benchmark = await create_benchmark_from_usage(traces)
    print(f"Generated: {benchmark.benchmark_id}")

asyncio.run(test())
```

## 📁 Key Files

- **Complete Integration**: `scripts/run_complete_integration.py`
- **ROMA Config**: `config/profiles/officeqa/default.yaml`
- **Arena Submission**: `config/profiles/officeqa/arena/`
- **Auto-Benchmark**: `src/roma_dspy/core/skills/automated_benchmark_generator.py`
- **GEPA Integration**: `src/roma_dspy/core/skills/gepa_integration.py`
- **EvoSkill**: `src/roma_dspy/core/skills/evoskill_integration.py`
- **Evidence Cards**: `src/roma_dspy/core/skills/evidence_card_system.py`