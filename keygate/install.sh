#!/usr/bin/env bash
# Put keygate in front of llama-swap:
#   clients ─► keygate 0.0.0.0:8080 (per-key model permissions, SQLite log) ─► llama-swap 127.0.0.1:8081
#
# Safe to re-run. On first run it also migrates the keys already in llama-swap's `apiKeys:` into keygate
# (allowed every model, so no client breaks) and replaces them with one internal key only keygate knows.
# Restarting llama-swap unloads whatever model is loaded, so run it when nothing is generating.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
cd "$(dirname "$0")"

LS_CONFIG=/etc/llama-swap/config.yaml
ENV=/etc/keygate/keygate.env

# 1. user, program, config
id keygate &>/dev/null || useradd --system --no-create-home --home-dir /var/lib/keygate --shell /usr/sbin/nologin keygate
install -m 0755 keygate.py /usr/local/bin/keygate
install -d -m 0750 -o root -g keygate /etc/keygate
if [[ ! -f $ENV ]]; then
  umask 027
  cat > "$ENV" <<EOF
KEYGATE_LISTEN=0.0.0.0:8080
KEYGATE_UPSTREAM=127.0.0.1:8081
# keygate sends this to llama-swap; it is llama-swap's only apiKey
KEYGATE_UPSTREAM_KEY=sk-$(openssl rand -hex 24)
KEYGATE_TIMEOUT=3600
EOF
  chown root:keygate "$ENV"
fi
UPSTREAM_KEY=$(sed -n 's/^KEYGATE_UPSTREAM_KEY=//p' "$ENV")
install -m 0644 keygate.service /etc/systemd/system/keygate.service
install -d -m 0700 -o keygate -g keygate /var/lib/keygate

before=$(cat "$LS_CONFIG" /etc/systemd/system/llama-swap.service.d/keygate.conf 2>/dev/null | sha256sum)

# 2. move llama-swap's keys into keygate; leave llama-swap only the internal key
grep -qF "$UPSTREAM_KEY" "$LS_CONFIG" || cp -p "$LS_CONFIG" "$LS_CONFIG.bak-pre-keygate-$(date +%Y%m%d-%H%M%S)"
python3 -I - "$LS_CONFIG" "$UPSTREAM_KEY" <<'EOF' | while read -r n key; do
import re, sys
path, internal = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if l.rstrip() == "apiKeys:")
end = start + 1
item = re.compile(r'^\s+-\s*["\']?([^"\'\s#]+)')
keys = []
while end < len(lines) and (lines[end].strip() == "" or lines[end].lstrip().startswith("#") or item.match(lines[end])):
    m = item.match(lines[end])
    if m: keys.append(m.group(1))
    end += 1
for n, k in enumerate([k for k in keys if k != internal], 1):
    print(n, k)
new = lines[:start + 1] + [f'  - "{internal}"  # keygate only; clients use keys managed with `keygate`\n', "\n"] + lines[end:]
open(path, "w").write("".join(new))
EOF
  echo "$key" | /usr/local/bin/keygate import "from llama-swap #$n" --models '*' || true
done

# 3. llama-swap moves to localhost:8081
install -d /etc/systemd/system/llama-swap.service.d
cat > /etc/systemd/system/llama-swap.service.d/keygate.conf <<'EOF'
# keygate owns :8080 and forwards here; llama-swap is reachable from this machine only
[Service]
ExecStart=
ExecStart=/usr/local/bin/llama-swap -config /etc/llama-swap/config.yaml -listen 127.0.0.1:8081
EOF
llama-swap -config "$LS_CONFIG" -validate

# config and its backups hold keys: llama-swap's user may read the config, nobody else; backups root-only
chown root:llama "$(dirname "$LS_CONFIG")" "$LS_CONFIG"
chmod 0750 "$(dirname "$LS_CONFIG")"
chmod 0640 "$LS_CONFIG"
find "$(dirname "$LS_CONFIG")" -maxdepth 1 -type f ! -path "$LS_CONFIG" -exec chown root:root {} + -exec chmod 0600 {} +

systemctl daemon-reload
after=$(cat "$LS_CONFIG" /etc/systemd/system/llama-swap.service.d/keygate.conf | sha256sum)
if [[ $before != "$after" ]]; then
  echo "llama-swap config changed: restarting it (unloads the current model)"
  systemctl restart llama-swap
fi
systemctl enable --now keygate
systemctl restart keygate
sleep 2
systemctl --no-pager --lines=3 status keygate
keygate list
