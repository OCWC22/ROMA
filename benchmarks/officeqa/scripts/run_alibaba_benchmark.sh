#!/usr/bin/env bash
# OfficeQA Model Studio (Alibaba) benchmark launcher
# Enables blazing fast execution spanning the full DAG using native APIs.
#
# Usage:
#   ./benchmarks/officeqa/scripts/run_alibaba_benchmark.sh [model] [subset] [methods]
#
# Examples:
#   ./benchmarks/officeqa/scripts/run_alibaba_benchmark.sh qwen3.5-plus bench5 roma_runtime
#   ./benchmarks/officeqa/scripts/run_alibaba_benchmark.sh glm-5 pro "roma_runtime,track_a_dspy_gepa"

set -euo pipefail

MODEL="${1:-qwen3.5-plus}"
SUBSET="${2:-bench5}"
METHODS="${3:-roma_runtime}"
PROFILE="officeqa/api_alibaba"
SOLVE_TIMEOUT=400     # API calls are extremely fast (~1-2s each)
OPTIMIZE_TIMEOUT=1800 # 30 min for optimization phase

# Ensure DASHSCOPE_API_KEY is available
if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
  echo "Error: DASHSCOPE_API_KEY environment variable is not set."
  echo "Please set it before running this script."
  echo "Example: export DASHSCOPE_API_KEY='your-key'"
  exit 1
fi

export ALIBABA_MODEL="$MODEL"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# The model might have invalid path characters, sanitize it for the folder
SAFE_MODEL=$(echo "$MODEL" | tr -d '.' | tr '-' '_')
OUTPUT_DIR="/tmp/officeqa_${SUBSET}_${SAFE_MODEL}_${TIMESTAMP}"
mkdir -p "$OUTPUT_DIR"

SPLIT_ARGS=""
case "$SUBSET" in
  bench5|smoke) SPLIT_ARGS="--train-size 0 --val-size 0" ;;
esac

echo "=== OfficeQA API Benchmark (Alibaba Cloud) ==="
echo "  Target Model:    $MODEL"
echo "  Subset:          $SUBSET"
echo "  Methods:         $METHODS"
echo "  Profile:         $PROFILE"
echo "  Output:          $OUTPUT_DIR"
echo ""

# shellcheck disable=SC2086
PYTHONPATH=src uv run python benchmarks/officeqa/scripts/officeqa_benchmark.py \
  --methods "$METHODS" \
  --subset "$SUBSET" \
  --model "$MODEL" \
  --cli api \
  --profile "$PROFILE" \
  --solve-timeout-seconds "$SOLVE_TIMEOUT" \
  --optimize-timeout-seconds "$OPTIMIZE_TIMEOUT" \
  --mode with_corpus \
  --output-dir "$OUTPUT_DIR" \
  $SPLIT_ARGS \
  2>&1 | tee "$OUTPUT_DIR/run.log"

echo ""
echo "Results saved to: $OUTPUT_DIR"
