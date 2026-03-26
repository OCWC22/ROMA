#!/usr/bin/env bash
# OfficeQA CLI benchmark launcher
# Uses correct timeouts and CLI-optimized profile for Claude Code / Codex backends.
#
# Usage:
#   ./benchmarks/officeqa/scripts/run_cli_benchmark.sh [claude|codex] [subset] [methods]
#
# Examples:
#   ./benchmarks/officeqa/scripts/run_cli_benchmark.sh claude bench5 roma_runtime
#   ./benchmarks/officeqa/scripts/run_cli_benchmark.sh codex pro "roma_runtime,track_a_dspy_program"
#
# Expected latency per question:
#   - roma_runtime: ~2-5 min (5 agent steps × 10-30s CLI calls + tool-use loops)
#   - rlm_runtime:  ~5-10 min (depth=3, more decomposition)
#   - Methods with --optimize: add 30-60 min optimization phase

set -euo pipefail

CLI="${1:-claude}"
SUBSET="${2:-bench5}"
METHODS="${3:-roma_runtime}"
PROFILE="officeqa/cli_optimized"
SOLVE_TIMEOUT=1800     # 30 min per question (CLI calls are extremely high latency)
OPTIMIZE_TIMEOUT=3600  # 1 hour for optimization phase

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="/tmp/officeqa_${SUBSET}_${CLI}_${TIMESTAMP}"
mkdir -p "$OUTPUT_DIR"

# Small subsets (bench5, smoke) have very few questions.
# Default train_size=20 would consume all of them, leaving 0 test questions.
SPLIT_ARGS=""
case "$SUBSET" in
  bench5|smoke) SPLIT_ARGS="--train-size 0 --val-size 0" ;;
esac

echo "=== OfficeQA CLI Benchmark ==="
echo "  CLI:             $CLI"
echo "  Subset:          $SUBSET"
echo "  Methods:         $METHODS"
echo "  Profile:         $PROFILE"
echo "  Solve timeout:   ${SOLVE_TIMEOUT}s"
echo "  Optimize timeout: ${OPTIMIZE_TIMEOUT}s"
echo "  Split override:  ${SPLIT_ARGS:-default}"
echo "  Output:          $OUTPUT_DIR"
echo ""

cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"

# shellcheck disable=SC2086
PYTHONPATH=src uv run python benchmarks/officeqa/scripts/officeqa_benchmark.py \
  --methods "$METHODS" \
  --subset "$SUBSET" \
  --cli "$CLI" \
  --profile "$PROFILE" \
  --solve-timeout-seconds "$SOLVE_TIMEOUT" \
  --optimize-timeout-seconds "$OPTIMIZE_TIMEOUT" \
  --mode with_corpus \
  --output-dir "$OUTPUT_DIR" \
  $SPLIT_ARGS \
  2>&1 | tee "$OUTPUT_DIR/run.log"

echo ""
echo "Results saved to: $OUTPUT_DIR"
