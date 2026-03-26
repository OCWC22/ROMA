import os
import dspy
import json
import csv
from dspy.teleprompt import GEPA

# 1. Setup Models
key = os.environ.get("DASHSCOPE_API_KEY")
if not key:
    raise ValueError("DASHSCOPE_API_KEY environment variable required")

# We use Alibaba's Qwen model or Kimi as the LLM
from roma_dspy.utils.alibaba_lm import AlibabaLM
lm = AlibabaLM(model="kimi-k2.5", api_key=key, max_tokens=1000, timeout=120)
dspy.settings.configure(lm=lm)

# Read the current prompt
prompt_path = "prompts/officeqa_prompt.j2"
with open(prompt_path, "r") as f:
    current_prompt = f.read()

# 2. Define the DSPy Signature mapping to our Arena Prompt
class ArenaSubmissionTask(dspy.Signature):
    question = dspy.InputField(desc="The grounded reasoning financial question")
    documents = dspy.InputField(desc="The relevant files to search")
    answer = dspy.OutputField(desc="A precise numerical value")

# Override the docstring with our actual J2 prompt
ArenaSubmissionTask.__doc__ = current_prompt

import tempfile
from pathlib import Path
from prompt_optimization import get_default_config
from prompt_optimization.solver_setup import create_benchmark_solver_module
from roma_dspy.officeqa import extract_officeqa_answer

class ArenaPromptEvaluator(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predictor = dspy.Predict(ArenaSubmissionTask)
        
    def forward(self, question, documents):
        # 1. GEPA mutated `self.predictor.signature.instructions`
        candidate_text = self.predictor.signature.instructions
        
        # 2. Write the mutated candidate to a temp j2 artifact for ROMA to consume
        with tempfile.NamedTemporaryFile(mode="w", suffix=".j2", delete=False) as handle:
            handle.write(candidate_text)
            temp_path = handle.name
            
        # 3. Create the ROMA + RLM solver configuration
        eval_config = get_default_config()
        eval_config.prompt_source_policy = "preserve_profile"
        eval_config.artifact_component = "planner"
        eval_config.artifact_path = temp_path
        eval_config.officeqa_artifact_component = "planner"
        eval_config.officeqa_artifact_path = temp_path
        
        # 4. We execute the hybrid ROMA + RLM (runtime.max_depth=3) Native Solver!
        module = create_benchmark_solver_module(
            eval_config,
            family="officeqa",
            profile="officeqa/api_alibaba",
            overrides=["runtime.max_depth=3"], # RLM Integration!
            lm_model="kimi-k2.5",
            lm_backend="api",
            runtime_options={"disable_filesystem_mcp": True, "enable_checkpoints": False},
        )
        
        # 5. Evaluate the J2 against the target question using full tool execution
        try:
            prediction = module(goal=question)
            raw_output = str(getattr(prediction, "result_text", prediction) or "")
            ans = extract_officeqa_answer(raw_output)
        except Exception as e:
            ans = ""
            print(f"Error evaluating candidate: {e}")
            
        return dspy.Prediction(answer=ans)

# 3. Load the Bench5 Data points for our optimizer
trainset = []
with open("data/officeqa/officeqa_bench5.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        # We simulate the search environment by feeding it the expected target files
        trainset.append(dspy.Example(
            question=row["question"],
            documents=row["source_files"],
            answer=row["answer"]
        ).with_inputs("question", "documents"))

# 4. Define our metric (Exact Match or 1% tolerance)
def numeric_tolerance_metric(example, pred, trace=None, pred_name=None, pred_trace=None):
    try:
        # Clean both expected and predicted strings
        exp_val = float(str(example.answer).replace(",", "").replace("$", ""))
        pred_val = float(str(pred.answer).replace(",", "").replace("$", ""))
        
        # Sentient Arena uses 1% fuzzy matching tolerance
        tolerance = exp_val * 0.01
        return abs(exp_val - pred_val) <= tolerance
    except Exception:
        return False

# 5. Initialize and run GEPA
print(f"Starting GEPA evolutionary optimization on {prompt_path}...")
print(f"Initial Prompt Length: {len(current_prompt)} chars")

optimizer = GEPA(
    metric=numeric_tolerance_metric,
    max_metric_calls=5, # Tiny budget for quick hackathon iteration
    num_threads=1,      # Sequential to avoid Dashscope rate limits
    track_stats=True,
    reflection_lm=lm
)

optimized_module = optimizer.compile(
    student=ArenaPromptEvaluator(),
    trainset=trainset
)

# 6. Extract the newly mutated prompt and write it back to the submission payload
new_prompt = optimized_module.predictor.signature.instructions

print("\n\n--- GEPA MUTATION COMPLETE ---")
print(f"New Prompt Length: {len(new_prompt)} chars")

with open(prompt_path, "w") as f:
    f.write(new_prompt)

print(f"Successfully overwrote {prompt_path} with the GEPA-optimized instructions!")
