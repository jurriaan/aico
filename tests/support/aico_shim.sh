#!/usr/bin/env bash
# Shim script to wrap the 'aico' binary for testing purposes.
#
# AICO_BINARY is expected to be set to the path of the actual 'aico' binary.
#
# This shim is used by functional tests to isolate the execution environment
# and provide a controlled PTY for interactive commands like 'aico edit'.

faketty() {
  script -qefc "$(printf "%q " "$@")" /dev/null
}

if [ "$1" = "edit" ]; then
  # Force TTY for 'edit' to test interactive logic via a PTY spawn
  # The 'tr -d \r' is crucial to normalize the PTY output for clitest comparison
  faketty "$AICO_BINARY" "$@" | tr -d '\r'
else
  # Standard execution for non-interactive commands
  "$AICO_BINARY" "$@"
fi
