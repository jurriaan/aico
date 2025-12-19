#!/bin/bash
set -e

# Ensure we have clitest
if ! command -v clitest >/dev/null 2>&1; then
    echo "Error: clitest not found. Please install it to run functional tests."
    exit 1
fi

# Create a temporary workspace
TEST_WORKSPACE=$(mktemp -d)

# Capture paths before moving to temporary workspace
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
FEATURES_DIR="$PROJECT_ROOT/tests/features"

# Start Mock LLM Server
python3 "$PROJECT_ROOT/tests/support/mock_llm.py" &
MOCK_PID=$!

# Cleanup trap
trap 'kill $MOCK_PID 2>/dev/null || true; rm -rf "$TEST_WORKSPACE"' EXIT

# Isolate environment
export HOME="$TEST_WORKSPACE"
export XDG_CONFIG_HOME="$TEST_WORKSPACE/.config"
export XDG_CACHE_HOME="$TEST_WORKSPACE/.cache"
export OPENAI_API_KEY="sk-test-key"
export OPENAI_BASE_URL="http://localhost:5005/v1"

# Populate Model Metadata Cache for deterministic status checks
mkdir -p "$XDG_CACHE_HOME/aico"
cat <<EOF > "$XDG_CACHE_HOME/aico/models.json"
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

# Move to workspace
cd "$TEST_WORKSPACE"

# and ensure we use the local version of the code via the shim.
mkdir -p "$TEST_WORKSPACE/bin"
REAL_AICO_ENTRY="$PROJECT_ROOT/src/aico/main.py"
SHIM_TEMPLATE="$PROJECT_ROOT/tests/support/aico_shim.sh"

cp "$SHIM_TEMPLATE" "$TEST_WORKSPACE/bin/aico"
# We need to bake the REAL_AICO_ENTRY path into the shim or pass it.
# Replacing the placeholder $1 wrapper logic for simplicity here:
cat <<EOF > "$TEST_WORKSPACE/bin/aico"
#!/bin/bash
"$SHIM_TEMPLATE" "$REAL_AICO_ENTRY" "\$@"
EOF

chmod +x "$TEST_WORKSPACE/bin/aico"

export PATH="$TEST_WORKSPACE/bin:$PATH"

# Run clitest against feature files in the project root

RETRY_COUNT=0
MAX_RETRIES=50
while ! curl -s http://localhost:5005/v1 > /dev/null 2>&1; do
    sleep 0.1
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ "$RETRY_COUNT" -ge "$MAX_RETRIES" ]; then
        echo "Error: Mock LLM server failed to start"
        exit 1
    fi
done

# Ensure the test workspace is trusted for addon execution
mkdir -p "$XDG_CONFIG_HOME/aico"
echo "$TEST_WORKSPACE" >> "$XDG_CONFIG_HOME/aico/trusted_paths"

# Explicitly unset inherited environment variables that could bias tests
unset AICO_SESSION_FILE
unset PAGER

# Check if the directory exists and contains markdown files before running clitest
if [ -d "$FEATURES_DIR" ]; then
    clitest "$FEATURES_DIR"/*.md
else
    echo "Error: Features directory not found at $FEATURES_DIR"
    exit 1
fi
