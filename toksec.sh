#!/bin/bash
# toksec.sh — measure real tokens/sec against a llama-server endpoint
# Usage: ./toksec.sh [port] [model] [max_tokens]

PORT="${1:-5802}"
MODEL="${2:-qwen3.8-27b}"
MAX="${3:-200}"

PROMPT="Write a short Python function that reverses a string and includes a docstring."

START=$(date +%s.%N)

RESP=$(curl -s "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL\",
    \"messages\": [{\"role\":\"user\",\"content\":\"$PROMPT\"}],
    \"max_tokens\": $MAX,
    \"stream\": false
  }")

END=$(date +%s.%N)

# Extract usage
PROMPT_TOK=$(echo "$RESP" | jq -r '.usage.prompt_tokens // 0')
COMP_TOK=$(echo "$RESP" | jq -r '.usage.completion_tokens // 0')
TOTAL_TOK=$(echo "$RESP" | jq -r '.usage.total_tokens // 0')

ELAPSED=$(echo "$END - $START" | bc -l)

if [ "$(echo "$ELAPSED > 0" | bc -l)" -eq 1 ] && [ "$COMP_TOK" -gt 0 ]; then
  GEN_RATE=$(echo "$COMP_TOK / $ELAPSED" | bc -l)
  echo "Prompt tokens:     $PROMPT_TOK"
  echo "Completion tokens: $COMP_TOK"
  echo "Elapsed:           $(printf '%.2f' "$ELAPSED") s"
  echo "Generation:        $(printf '%.1f' "$GEN_RATE") tok/s"
else
  echo "Request failed or no completion tokens."
  echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
fi
