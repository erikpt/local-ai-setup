#!/usr/bin/env bash
set -euo pipefail

CONFIG="/etc/llama-swap/config.yaml"
NEWKEY="${1:-sk-$(openssl rand -hex 24)}"

if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG" >&2
  exit 1
fi

# Add the key if it isn't already present
if grep -qF "$NEWKEY" "$CONFIG"; then
  echo "Key already in config, skipping."
else
  # Append under apiKeys: (creates the section if missing)
  if grep -q '^apiKeys:' "$CONFIG"; then
    # Insert after the apiKeys: line
    awk -v key="$NEWKEY" '
      /^apiKeys:/ { print; print "  - \"" key "\""; next }
      { print }
    ' "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
  else
    # No apiKeys section yet — add it at the top
    printf 'apiKeys:\n  - "%s"\n\n' "$NEWKEY" | cat - "$CONFIG" > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
  fi
  echo "Added key: $NEWKEY"
fi

# Reload llama-swap
PID=$(pgrep -f 'llama-swap.*config.yaml' | head -1)
if [[ -n "$PID" ]]; then
  echo "Sending SIGHUP to llama-swap (pid $PID)"
  kill -HUP "$PID"
  echo "Reloaded. New key should be active."
else
  echo "llama-swap not found — start it manually."
fi
