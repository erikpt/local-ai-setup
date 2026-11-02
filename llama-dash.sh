#!/bin/bash
# llama-dash-multi.sh — GPU + CPU + tokens/s + throttle flags
# Usage: ./llama-dash-multi.sh 5801 5802

PORTS=("$@")
if [ ${#PORTS[@]} -eq 0 ]; then
  PORTS=(5801)
fi

declare -A psec_sum gsec_sum samples
declare -A prev_idle prev_total
declare -A prev_throttle

ncores=$(nproc)
for ((i=0; i<ncores; i++)); do
  prev_idle[$i]=0
  prev_total[$i]=0
  prev_throttle[$i]=0
done

# NVIDIA throttle reason decoder
decode_gpu_throttle() {
  local hex=$1
  local val=$((hex))
  local reasons=()
  (( val & 0x1 ))   && reasons+=("GPU idle")
  (( val & 0x2 ))   && reasons+=("Applications clocks setting")
  (( val & 0x4 ))   && reasons+=("SW power cap")
  (( val & 0x8 ))   && reasons+=("HW slowdown")
  (( val & 0x10 ))  && reasons+=("Sync boost")
  (( val & 0x20 ))  && reasons+=("SW thermal slowdown")
  (( val & 0x40 ))  && reasons+=("HW thermal slowdown")
  (( val & 0x80 ))  && reasons+=("HW power brake slowdown")
  (( val & 0x100 )) && reasons+=("Display clock setting")
  (( val & 0x200 )) && reasons+=("Board limit")
  (( val & 0x400 )) && reasons+=("Reliability")
  if [ ${#reasons[@]} -eq 0 ]; then
    echo "unknown/residual ($hex)"
  else
    local IFS=", "
    echo "${reasons[*]}"
  fi
}

while true; do
  clear
  echo "=== llama.cpp dashboard  $(date '+%H:%M:%S') ==="
  echo

  # Load averages
  read -r load1 load5 load15 _ < /proc/loadavg
  printf "Load avg:  %s  %s  %s\n" "$load1" "$load5" "$load15"
  echo

  # CPU temps
  echo "--- CPU ---"
  pkg_temp=0
  if command -v sensors >/dev/null 2>&1; then
    sensors 2>/dev/null | grep -E 'Package id|Core [0-9]' | head -8
    pkg_temp=$(sensors 2>/dev/null | awk '/Package id/ {gsub(/[^0-9.]/,"",$4); print int($4); exit}')
  else
    for z in /sys/class/thermal/thermal_zone*/temp; do
      [ -f "$z" ] || continue
      type=$(cat "${z%/*}/type" 2>/dev/null)
      temp=$(cat "$z" 2>/dev/null)
      [ -n "$temp" ] && printf "%s: %.1f°C  " "$type" "$(echo "$temp/1000" | bc -l)"
    done
    echo
  fi

  # CPU throttle check (only on rising counter or hot + loaded)
  cpu_throttle=0
  i=0
  for f in /sys/devices/system/cpu/cpu*/thermal_throttle/core_throttle_count; do
    [ -f "$f" ] || continue
    count=$(cat "$f" 2>/dev/null || echo 0)
    prev=${prev_throttle[$i]:-0}
    if [ "$count" -gt "$prev" ]; then
      cpu_throttle=1
    fi
    prev_throttle[$i]=$count
    i=$((i+1))
  done
  # Also flag if package is hot and cores are busy
  if [ "${pkg_temp:-0}" -ge 75 ]; then
    busy=0
    for ((c=0; c<ncores; c++)); do
      # rough: if we saw non-zero usage recently we consider it loaded
      busy=1
    done
    [ "$busy" -eq 1 ] && cpu_throttle=1
  fi
  [ "$cpu_throttle" -eq 1 ] && echo "*** CPU THERMAL THROTTLE DETECTED ***"

  # Per-core usage
  echo
  echo "Per-core %:"
  core=0
  while read -r cpu user nice system idle iowait irq softirq steal rest; do
    [[ $cpu == cpu[0-9]* ]] || continue
    total=$((user+nice+system+idle+iowait+irq+softirq+steal))
    idle_d=$((idle - ${prev_idle[$core]:-0}))
    total_d=$((total - ${prev_total[$core]:-0}))
    if [ "$total_d" -gt 0 ]; then
      usage=$(echo "100 * ($total_d - $idle_d) / $total_d" | bc)
    else
      usage=0
    fi
    printf "c%-2d:%3d%%  " "$core" "$usage"
    prev_idle[$core]=$idle
    prev_total[$core]=$total
    core=$((core+1))
    [ $((core % 6)) -eq 0 ] && echo
  done < /proc/stat
  echo
  echo

  # GPU
  echo "--- GPU ---"
  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu \
             --format=csv,noheader,nounits 2>/dev/null | \
  awk -F', ' '{printf "Util: %s%%  VRAM: %s / %s MiB  Power: %s W  Temp: %s°C\n", $1,$2,$3,$4,$5}'

  # GPU throttle check (decoded)
  gpu_hex=$(nvidia-smi --query-gpu=clocks_throttle_reasons.active --format=csv,noheader 2>/dev/null)
  if [ -n "$gpu_hex" ] && [ "$gpu_hex" != "Not Active" ] && [ "$gpu_hex" != "0x0000000000000000" ]; then
    decoded=$(decode_gpu_throttle "$gpu_hex")
    echo "*** GPU THROTTLE: $decoded ***"
  fi
  echo

  # Per-port tokens
  for PORT in "${PORTS[@]}"; do
    URL="http://127.0.0.1:${PORT}/metrics"
    echo "--- Port $PORT ---"
    if curl -sf "$URL" >/tmp/llama-metrics.$$ 2>/dev/null; then
      eval $(grep -E 'llamacpp:prompt_tokens_seconds|llamacpp:tokens_predicted_seconds' /tmp/llama-metrics.$$ | \
             sed 's/^#.*//' | sed 's/.*{[^}]*} //' | \
             awk '
               /prompt_tokens_seconds/ {print "psec="$2}
               /tokens_predicted_seconds/ {print "gsec="$2}
             ')
      psec=${psec:-0}
      gsec=${gsec:-0}
      samples[$PORT]=$(( ${samples[$PORT]:-0} + 1 ))
      psec_sum[$PORT]=$(echo "${psec_sum[$PORT]:-0} + $psec" | bc -l)
      gsec_sum[$PORT]=$(echo "${gsec_sum[$PORT]:-0} + $gsec" | bc -l)
      avg_p=$(echo "${psec_sum[$PORT]} / ${samples[$PORT]}" | bc -l)
      avg_g=$(echo "${gsec_sum[$PORT]} / ${samples[$PORT]}" | bc -l)
      printf "  Prompt:   %6.1f tok/s   (avg %6.1f)\n" "$psec" "$avg_p"
      printf "  Generate: %6.1f tok/s   (avg %6.1f)\n" "$gsec" "$avg_g"
      rm -f /tmp/llama-metrics.$$
    else
      echo "  (no metrics)"
    fi
    echo

    # inside the per-port loop
    if ! curl -sf --max-time 5 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      echo "  *** MODEL UNREACHABLE / CRASHED ***"
    fi
  done

  echo "Press Ctrl-C to exit"
  sleep 2
done
