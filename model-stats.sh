#!/usr/bin/env bash
# model-stats.sh — benchmark results for the local llama-swap models.
# Measured 2026-11-01/02 on: RTX 4090 24 GB, i7-8700K, 64 GB DDR4, PCIe Gen3.
# All runs: 128K context, --parallel 1, flash attention, q8_0 K cache.
#   pp  = prompt processing (tok/s)   gen = generation (tok/s)
#   ~11K / ~80K = prompt size in tokens
#   code = 5 coding tasks x 3 samples, verified by unit tests (small sample!)
# Usage: ./model-stats.sh [--all]   (--all also shows removed/old configs)

if [[ -t 1 ]]; then
  B=$'\e[1m'; D=$'\e[2m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
else
  B= D= G= Y= R= C= N=
fi

# name | file/quant | pp@11K | pp@80K | gen@11K | gen@80K | VRAM GB | code | status
ACTIVE=(
  "qwen3-coder-next|Coder-Next UD-Q3_K_XL|1507|1574|37.8|34.1|22.6|12/15|default for OpenCode"
  "qwen3-coder-next-q4|Coder-Next UD-Q4_K_XL|940|1004|31.7|29.5|21.7|12/15|higher-bit, slower"
  "qwen3.8-27b|Qwen3.8 27B UD-Q5_K_M|2650|1990|37.8|24.3|22.5|13/15|best code score; Hermes"
  "qwen3.8-27b-heretic|Qwen3.8 27B Heretic Q4_K_M|2762|2035|45.9|36.7|20.8|11/15|uncensored"
)
REMOVED=(
  "coder-next (old cfg)|Coder-Next Q3, --n-cpu-moe 40|226|-|27.4|-|10.2|-|before tuning (7x slower)"
  "coder-next-abliterated|huihui Q3_K_M|1486|1560|48.8|43.1|22.3|9/15|deleted"
  "coder-next-heretic|Heretic i1-IQ4_XS|1153|1230|39.3|35.8|22.1|9/15|deleted"
)

color_code() {  # colour the coding score
  local n=${1%%/*}
  [[ $n == - ]] && { printf '%s' "$D-$N"; return; }
  if   (( n >= 13 )); then printf '%s' "$G$1$N"
  elif (( n >= 11 )); then printf '%s' "$Y$1$N"
  else                     printf '%s' "$R$1$N"; fi
}

row() {
  IFS='|' read -r name quant pp1 pp2 g1 g2 vram code status <<<"$1"
  printf "  %-24s %-30s %7s %7s %6s %6s %6s  " "$name" "$quant" "$pp1" "$pp2" "$g1" "$g2" "$vram"
  color_code "$code"
  printf "   %s\n" "$D$status$N"
}

header() {
  printf "  ${B}%-24s %-30s %7s %7s %6s %6s %6s  %-5s   %s${N}\n" \
    "llama-swap name" "model / quant" "pp@11K" "pp@80K" "gen11K" "gen80K" "VRAM" "code" "notes"
  printf "  ${D}%s${N}\n" "$(printf '%.0s─' {1..118})"
}

echo
echo "  ${B}${C}Local model benchmarks${N}  ${D}RTX 4090 24GB · i7-8700K · 64GB DDR4 · PCIe Gen3 · 128K ctx${N}"
echo
header
for r in "${ACTIVE[@]}"; do row "$r"; done

if [[ ${1:-} == --all ]]; then
  echo
  echo "  ${B}Removed / historical${N}"
  header
  for r in "${REMOVED[@]}"; do row "$r"; done
fi

cat <<EOF

  ${B}Time to first token, cold 80K prompt:${N}  27B ~40s · Coder-Next Q3 ~50s · Coder-Next Q4 ~80s
  ${D}Follow-up turns reuse the prompt cache, so only new tokens are processed.
  Coding scores are 15 samples — differences of 1–2 are within noise.
  Only one model fits in VRAM; switching models takes ~30–60s.${N}
EOF
[[ ${1:-} == --all ]] || echo "  ${D}Run with --all to include removed models and the pre-tuning config.${N}"

# Live status from llama-swap, if reachable and a key is available
KEY=${LLAMA_SWAP_KEY:-$(sudo -n grep -oE 'sk-[a-f0-9]+' /etc/llama-swap/config.yaml 2>/dev/null | head -1)}
if [[ -n $KEY ]] && RUN=$(curl -sf -m 3 -H "Authorization: Bearer $KEY" localhost:8080/running 2>/dev/null); then
  loaded=$(echo "$RUN" | jq -r '[.running[]? | "\(.model) (\(.state))"] | join(", ")' 2>/dev/null)
  vram=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null | awk -F', ' '{printf "%.1f / %.1f GB", $1/1024, $2/1024}')
  echo
  echo "  ${B}Now:${N} loaded: ${loaded:-${D}none${N}}   VRAM: $vram"
fi
echo
