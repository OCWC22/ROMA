# OfficeQA Arena Competition — ROMA Virtual REPL Approach (Compact Context)

## What We're Doing

We're competing in **Sentient Arena's OfficeQA challenge** ($45K+ prize). The task: answer 246 financial questions (133 hard, 113 easy) about U.S. Treasury Bulletin PDFs (1939–2025). Scoring: fuzzy numeric matching at 1% tolerance. We can ONLY modify YAML config, Jinja2 prompt templates, and skill files — no custom Python agent code. We pick a pre-built coding agent harness (OpenCode, Codex, Goose, or OpenHands) and configure it.

## Our Submission Structure

```
officeqa-arena/
├── arena.yaml              # Config: opencode harness, claude-sonnet-4.5, MCP filesystem, 8GB, 540s timeout
├── prompts/system.j2       # Jinja2 prompt template ({{ instruction }} variable) — the brain
└── skills/                 # 7 reference files copied into agent's skill directory
    ├── 01_scoring_exploit.md        # How score_answer() fuzzy matcher works
    ├── 02_treasury_navigation.md    # File layout: transformed/*.txt has markdown tables
    ├── 03_computation_patterns.md   # Formula templates: geometric mean, KL divergence, regression, CAGR, Zipf
    ├── 04_hard_question_strategy.md # Attack playbook, traps, time budgets
    ├── 05_table_parsing.md          # Markdown table extraction, OCR artifact handling
    ├── 06_answer_extraction_template.py  # Python utility (agent can copy to /tmp if needed)
    └── 07_virtual_repl_protocol.md  # ROMA role-cycling protocol (the key innovation)
```

## The Virtual REPL Protocol (Core Innovation)

We mapped **ROMA's recursive state machine** (4 specialized LLM roles) into a pure-prompt protocol. No ROMA Python runtime needed. The agent follows this cycle in structured XML tags:

**ROMA's actual code path** (`RecursiveSolver._async_execute_state_machine`):
```
PENDING → Atomizer (atomic or decompose?) →
  EXECUTE path: Executor → store result → COMPLETED
  PLAN path:   Planner → subtask graph → recurse each → Aggregator → COMPLETED
```

**Our prompt replicates it with tags:**
```
<ATOMIZER> → is_atomic? yes/no
  yes → <EXECUTOR> read file via MCP, extract base number → FINAL_ANSWER
  no  → <PLANNER> emit subtasks with dependency graph →
        <EXECUTOR task="0"> ... <EXECUTOR task="1"> ... →
        <AGGREGATOR> synthesize → FINAL_ANSWER
```

**State tracking** via `<REPL_STATE>` tags (mirrors ROMA's ContextStore) — compressed to ≤2 sentences per subtask to prevent context blowup. Max depth 3, then force-execute.

This is inspired by **RLM** (Recursive Language Models, MIT CSAIL) which uses LLM + Python REPL to recursively slice massive corpora. We get the same recursive decomposition but the LLM does computation in chain-of-thought instead of executing code. The agent still reads REAL files via MCP filesystem tools.

## The Scoring Exploit (Biggest Edge)

The `score_answer()` function compares **BASE NUMBERS ONLY**:
- Table says "36,080" with header "in millions" → ground truth is `36080`
- If you expand to `36080000000` → **FAIL** (999999x mismatch)
- **NEVER expand units** — this single rule is worth +15-20% accuracy
- Years (1900-2100) auto-filtered from predictions — safe in reasoning
- Greedy extraction: scorer scans your ENTIRE response for numbers, matches any against ground truth
- Multi-number answers: ALL ground truth numbers must appear somewhere in response

## What We Can Tune (YAML + Prompts Only)

1. **arena.yaml**: harness choice, model, MCP servers, memory, timeout, reasoning_effort
2. **prompts/system.j2**: the entire agent instruction set (ROMA role cycling, formatting rules, computation guidelines)
3. **skills/*.md**: reference documents loaded into agent context (scoring rules, navigation, math patterns, strategies)

## Prompt Optimization Tools Available

| Tool | What It Does | How It Helps |
|------|-------------|--------------|
| **GEPA/GEPA+** (DSPy) | Evolutionary prompt optimization with Pareto selection + LLM reflection | Auto-evolves our system.j2 and skill prompts per ROMA role (planner_only, executor_only, round_robin selectors) |
| **optimize_anything** | Hosted GEPA+ API | One-command optimization from Arena CLI |
| **EvoSkill** (Sentient) | Automated skill generation/evolution | Could auto-generate new skill files for skills/ |
| **Evolver** | General prompt evolution | Alternative to GEPA for prompt mutation |

GEPA+ integration is native in ROMA: `prompt_optimization/optimizer.py` creates a GEPA optimizer, `component_selectors.py` picks which role to optimize, `solver_setup.py` builds the solver module. The optimizer runs the agent on training questions, grades each role's contribution via a ComponentJudge, then mutates the weakest role's prompt.

## Questions for Improvement

1. **Model selection**: Claude Sonnet 4.5 ($$$) vs GPT-5.3-codex vs free open-source (qwen/qwen3-coder, deepseek/deepseek-v3.2, z-ai/glm-5 on OpenRouter)? Budget is ~$300 total credits. What's the best accuracy/cost tradeoff for heavy table parsing + math reasoning?

2. **Verifier role**: ROMA has a 5th role (VerifierSignature: verdict bool + feedback). Should we add `<VERIFIER>` as step 5 to catch unit expansion errors and wrong-cell extraction before outputting FINAL_ANSWER? Trade-off: extra tokens per question.

3. **GEPA+ config**: We have `component_selector` options: planner_only, executor_only, aggregator_only, round_robin. For OfficeQA where the bottleneck is accurate table extraction + unit handling, should we focus on executor_only? Or round_robin across all roles? How many `max_metric_calls` iterations before diminishing returns?

4. **Skill evolution**: Can EvoSkill or Evolver auto-generate better skill files from failed questions? E.g., run 10 questions → analyze failures → generate new `skills/08_common_failures.md` with specific correction patterns?

5. **MCP server choice**: Currently using `@anthropic/mcp-filesystem`. Would adding a search-oriented MCP server (e.g., `@anthropic/mcp-web-search` for cross-referencing, or a custom grep MCP) improve retrieval on multi-document questions?

6. **Harness comparison**: OpenCode vs Codex vs OpenHands-SDK vs Goose — which handles long structured prompts (our ROMA role cycling) best? Does reasoning_effort: "high" actually change behavior across harnesses?

7. **Transfer learning**: If we optimize skills/prompts for OfficeQA, how portable are they to other document-QA benchmarks (FRAMES, SimpleQA, SEAL-0)? ROMA's prompt_optimization already has dataset loaders for all of these.

8. **Automated eval loop**: Can we set up: run 10 questions → score → GEPA+ mutates prompts → run 10 different questions → repeat? What's the minimum viable feedback loop that improves overnight without burning credits?

---

## Appendix: Actual arena.yaml

```yaml
name: "officeqa-roma-killer"
version: "1.0.0"
competition: "officeqa"
agent:
  type: "harness"
  harness_name: "opencode"
  model: "anthropic/claude-sonnet-4-5-20250929"
  prompt_template_path: "prompts/system.j2"
  skills_dir: "skills/"
  mcp_servers:
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@anthropic/mcp-filesystem", "/app", "/tmp"]
  config:
    reasoning_effort: "high"
  env:
    OPENROUTER_API_KEY: "${oc.env:OPENROUTER_API_KEY,''}"
    ANTHROPIC_API_KEY: "${oc.env:ANTHROPIC_API_KEY,''}"
    OPENAI_API_KEY: "${oc.env:OPENAI_API_KEY,''}"
environment:
  memory: "8G"
  timeout_per_task: 540
```

## Appendix: Actual system.j2 (abbreviated key sections)

```jinja
You are a ROMA Virtual-REPL agent solving OfficeQA.
Cycle roles: Atomizer → Planner → Executor → Aggregator → repeat.

# ANSWER FORMATTING (non-negotiable)
1. NEVER expand units. "36,080" with "in millions" header → answer 36080, NOT 36080000000.
2. Strip commas/dollar signs. Preserve source precision. Percentages without %.
3. Unicode minus → hyphen. List answers: ALL numbers must appear.

# ENVIRONMENT
Treasury docs in: transformed/ (markdown tables, USE FIRST), parsed/ (JSON), raw/ (PDFs)

# TASK
{{ instruction }}

# VIRTUAL REPL EXECUTION
<REPL_STATE>depth: 0, status: PENDING</REPL_STATE>

STEP 1 — ATOMIZER: is_atomic? → EXECUTE or PLAN
STEP 2 — PLANNER (if non-atomic): subtasks with deps, types: RETRIEVE/THINK/WRITE  
STEP 3 — EXECUTOR: read files via MCP, extract base numbers, CoT math
STEP 4 — AGGREGATOR: synthesize, verify units, check magnitude
STEP 5 — FINAL_ANSWER: <base number>

Context compression: ≤2 sentences per subtask result. Max depth 3 then force-execute.
```

## Appendix: Sentient Cohort Zero Context

**Competition**: Sentient Arena OfficeQA campaign, March 14 – April 4 2026, 115 cohort members, $45K+ prizes.

**Rules**: Pick a harness (OpenCode/Codex/Goose/OpenHands), configure via arena.yaml + prompt template + skills. No custom Python agent code. Submit via `arena submit`, scored on full 246 questions.

**Resources**: $100 OpenRouter + $100 Daytona + $100 Dedalus per team.

**Research directions from organizers**:
1. AI self-improvement / evolution (GEPA+, EvoSkill, optimize_anything, Evolver)
2. Transfer learning — can OfficeQA skills generalize to FRAMES/SimpleQA/SEAL-0?
3. Automated evaluation — auto-generate benchmarks for evolution feedback loops

**Key recommendation**: Iterate on 1-10 questions at a time. Don't burn credits on full dataset.

**Our approach combines all 3 research directions**: ROMA's recursive architecture (direction 1 via GEPA+), skill files designed to be benchmark-portable (direction 2), and the Virtual REPL protocol enables automated eval by structuring agent reasoning into gradable role outputs (direction 3).

## Appendix: RLM vs ROMA vs Our Virtual REPL — Side-by-Side

| Aspect | RLM (MIT CSAIL) | ROMA (Sentient) | Our Virtual REPL |
|--------|-----------------|-----------------|------------------|
| Recursion target | Context/data (LLM writes Python to slice corpus) | Task/problem (hierarchical subtask tree) | Task/problem via prompt tags |
| Requires sandbox? | Yes (Docker/E2B) | Yes (Python runtime) | No — pure prompt |
| State machine | LLM decides decomposition via code | Atomizer→Planner→Executor→Aggregator (solve.py) | Same 4 roles as XML tags in system.j2 |
| Context management | Real Python REPL variables | ContextStore + XML context (models.py) | `<REPL_STATE>` tags, ≤2 sentences per result |
| Depth control | Code-level recursion limit | `max_depth` config, force-execute at limit | Depth 3 force-execute in prompt |
| Optimization | Manual prompt engineering | GEPA+ evolves each role's prompt independently | GEPA+ compatible (structured role outputs) |
| File access | os.walk, pandas.read_csv in sandbox | FileToolkit, MCPToolkit (runtime tools) | MCP filesystem server (reads real files) |
| Computation | Real numpy/scipy execution | Real code via E2B/CodeAct | Chain-of-thought using formula patterns |
| OfficeQA fit | Best for raw corpus traversal | Best for task orchestration | Both — decomposes tasks AND navigates corpus |

## Appendix: Key Skill File Summaries

**01_scoring_exploit.md**: The scorer extracts ALL numbers greedily from your response, filters years 1900-2100, compares base numbers only (never expanded units). Commas/$/%/Unicode minus all cleaned. Multi-number answers need ALL GT numbers present. Tolerance tiers: 0%, 0.1%, 1%, 5%.

**02_treasury_navigation.md**: Corpus = `transformed/treasury_bulletin_YYYY_MM.txt` (markdown tables). Use grep to find tables, sed to read ranges. Common locations: public debt (early pages), revenue (monthly statement sections), interest rates (average rates tables), international (TIC data).

**03_computation_patterns.md**: 10 Python-style patterns the LLM uses as CoT templates: table lookup, percentage change, geometric mean (exp(mean(ln(v)))), linear regression (linregress), KL divergence (Σ p·ln(p/q)), coefficient of variation (std/mean×100), CAGR ((end/start)^(1/n)-1), Zipf exponent (curve_fit), multi-doc aggregation, inflation adjustment (CPI ratio).

**04_hard_question_strategy.md**: Decompose question first (date, metric, computation, rounding). Time budget: easy 2min, hard 5-7min, never >8min. Traps: "in millions" means already in millions; fiscal year ≠ calendar year; net ≠ gross; revised vs preliminary data.

**07_virtual_repl_protocol.md**: Full ROMA state machine in structured tags. ATOMIZER outputs is_atomic + node_type. PLANNER outputs subtasks with goals/types/deps matching ROMA's SubTask model. EXECUTOR reads files or does CoT math. AGGREGATOR synthesizes + verifies units. REPL_STATE tracks compressed working memory. Depth 3 = force-execute.

## What I Need Help With

Given the constraints (YAML + prompts + skills only, ~$300 budget, 3 weeks, 246 questions scored at 1% tolerance):

1. **What's the highest-leverage change** to improve accuracy on the 133 hard questions?
2. **Which GEPA+ component_selector** should we use? The bottleneck seems to be Executor (table extraction + unit handling) rather than Planner (decomposition).
3. **Should we add a Verifier step** (ROMA supports it) to catch unit expansion errors before FINAL_ANSWER?
4. **Model choice**: Claude Sonnet 4.5 is best for reasoning but expensive. Can we use a cheaper model (qwen3-coder, glm-5) for the Atomizer/Planner/Aggregator roles and only use Sonnet for Executor? (This is exactly how ROMA's config works — different models per role.)
5. **How to structure the GEPA+ feedback loop**: Run 10 questions → score → mutate prompts → repeat. What's the minimum iteration count that shows meaningful improvement?
6. **Can EvoSkill auto-generate failure-specific skill files** from wrong answers? E.g., "you failed geometric mean questions → here's a new skill with 5 worked examples."
