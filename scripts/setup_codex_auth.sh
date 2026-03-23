#!/bin/bash
# ==============================================================================
# setup_codex_auth.sh — Setup Codex CLI auth for ROMA integration
# ==============================================================================
#
# This configures Codex CLI authentication so we can use the subscription
# instead of direct API keys.
#
# Usage:
#   ./setup_codex_auth.sh
#
# After running, all ROMA/GEPA/RLM tools will use Codex CLI auth.
# ==============================================================================

set -euo pipefail

echo "=== Codex CLI Auth Setup ==="
echo ""

# --- Node.js 22 ---
echo "[1/5] Checking Node.js 22..."
if ! command -v node &>/dev/null || [[ "$(node --version)" != v22* ]]; then
    echo "  Installing Node.js 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
else
    echo "  Node.js $(node --version) already installed"
fi

# --- Codex CLI ---
echo "[2/5] Installing Codex CLI..."
if ! command -v codex &>/dev/null; then
    sudo npm install -g @openai/codex
else
    echo "  Codex $(codex --version) already installed"
fi

# --- Claude Code CLI (for Anthropic) ---
echo "[3/5] Checking Claude Code CLI..."
if ! command -v claude &>/dev/null; then
    echo "  Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
else
    echo "  Claude Code already installed"
fi

# --- Auth ---
echo "[4/5] Setting up authentication..."
echo ""
echo "  IMPORTANT: You need to authenticate with your subscription:"
echo ""
echo "  For OpenAI Codex:"
echo "    export OPENAI_API_KEY='sk-proj-...'"
echo "    echo \"\$OPENAI_API_KEY\" | codex login --with-api-key"
echo ""
echo "  For Anthropic Claude:"
echo "    claude login"
echo ""

# --- Verify ---
echo "[5/5] Verifying setup..."
echo ""
echo "  Node.js:  $(node --version 2>/dev/null || echo 'MISSING')"
echo "  npm:      $(npm --version 2>/dev/null || echo 'MISSING')"
echo "  Codex:    $(codex --version 2>/dev/null || echo 'MISSING')"
echo "  Claude:   $(claude --version 2>/dev/null || echo 'MISSING')"
echo ""

echo "=== Setup complete ==="
echo ""
echo "Next: Run the auth commands above, then use:"
echo "  uv run python scripts/run_complete_integration.py --mode test"