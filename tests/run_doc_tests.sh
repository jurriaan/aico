#!/bin/bash
set -e

# Locate Project Root (aico/)
# Script is expected to be in aico/tests/
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
FEATURES_DIR="$PROJECT_ROOT/docs"

# 1. Build the project (workspace builds both aico and mock_server)
echo "Building workspace (debug)..."
cd "$PROJECT_ROOT"
cargo build --quiet --workspace

# 2. Setup Test Workspace
TEST_WORKSPACE=$(mktemp -d)
trap 'rm -rf "$TEST_WORKSPACE"' EXIT

# 3. Configure Environment
export COLUMNS=80
export AICO_COLUMNS=80
export HOME="$TEST_WORKSPACE"
export XDG_CONFIG_HOME="$TEST_WORKSPACE/.config"
export XDG_CACHE_HOME="$TEST_WORKSPACE/.cache"

# Force aico to use the mock server (base url overwritten by mock_server)
export OPENAI_API_KEY="sk-test-key"
export OPENAI_BASE_URL="http://localhost:5005/v1" 

# 4. Link Compiled Binary and Shim
mkdir -p "$TEST_WORKSPACE/bin"
# Use debug build for speed during dev testing
ln -sf "$PROJECT_ROOT/target/debug/aico" "$TEST_WORKSPACE/bin/aico_bin"
export AICO_BINARY="$TEST_WORKSPACE/bin/aico_bin"
cp "$PROJECT_ROOT/tests/support/aico_shim.sh" "$TEST_WORKSPACE/bin/aico"
chmod +x "$TEST_WORKSPACE/bin/aico"
export PATH="$TEST_WORKSPACE/bin:$PATH"

# Populate Model Metadata Cache for deterministic status and cost checks
mkdir -p "$XDG_CACHE_HOME/aico"
cat <<EOF >"$XDG_CACHE_HOME/aico/models.json"
{
  "last_fetched": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "models": {
    "openai/test-model": {
      "input_cost_per_token": 0.001,
      "output_cost_per_token": 0.002,
      "max_input_tokens": 1000
    }
  }
}
EOF

# 5. Move to Test Workspace to prevent polluting the project root
# This ensures .aico and .ai_session.json are created in the temp folder
cd "$TEST_WORKSPACE"

# Clean session env vars that might leak
unset AICO_SESSION_FILE

if [ $# -gt 0 ]; then
  # If absolute paths were passed, use them; otherwise they are relative to PROJECT_ROOT
  FILES="$@"
else
  FILES="$FEATURES_DIR/*.md"
fi

FOUND=0
for f in $FILES; do
  [ -e "$f" ] || continue
  FOUND=1
  echo
  echo "----------------------------------------------------------------"
  echo "Testing: $(basename "$f")"
  echo "----------------------------------------------------------------"

  # Clean local state between files (now inside TEST_WORKSPACE)
  rm -rf .ai_session.json .aico

  # Run clitest - $f is an absolute path to the docs folder,
  # but clitest will execute the commands in the CWD ($TEST_WORKSPACE)
  #
  # clitest is force-ran using bash as on GitHub Actions hangs otherwise.
  "$PROJECT_ROOT/target/debug/mock_server" bash clitest "$f"
done

if [ "$FOUND" -eq 0 ]; then
  echo "Error: No test files found matching: $FILES"
  exit 1
fi

echo ""
echo "All doc tests passed!"
