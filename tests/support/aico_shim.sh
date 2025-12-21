#!/bin/sh
# This shim is used by functional tests to isolate the execution environment
# and provide a controlled PTY for interactive commands like 'aico edit'.

REAL_AICO_ENTRY="$1"
shift

PYTHONPATH="$(dirname "$(dirname "$(dirname "$REAL_AICO_ENTRY")")")/src:$PYTHONPATH"
export PYTHONPATH

# Ensure dependencies are available
. "$(dirname "$(dirname "$(dirname "$REAL_AICO_ENTRY")")")/.venv/bin/activate"

if [ "$1" = "edit" ]; then
  # Force TTY for 'edit' to test interactive logic via a PTY spawn
  # The 'tr -d \r' is crucial to normalize the PTY output for clitest comparison
  # We pass the full command to pty.spawn, excluding the first shim arg but including the real aico command
  python -c "import pty, sys, os; pty.spawn([sys.executable, '$REAL_AICO_ENTRY'] + sys.argv[1:])" "$@" | tr -d '\r'
else
  # Standard execution for non-interactive commands
  python "$REAL_AICO_ENTRY" "$@"
fi
