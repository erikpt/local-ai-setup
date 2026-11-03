# keygate

API keys with **per-model permissions** for [llama-swap](https://github.com/mostlygeek/llama-swap), which on its own
only has all-or-nothing keys. One Python file, standard library and SQLite only: nothing to `pip install`, so no
third-party supply chain to worry about.

```
clients ──► keygate 0.0.0.0:8080 ──► llama-swap 127.0.0.1:8081 ──► llama-server / ComfyUI / Chatterbox
            1. is the key valid?
            2. may it use the requested model?
            3. forward with llama-swap's internal key, stream the reply back
            4. log the request to SQLite
```

## Commands

```bash
sudo keygate add "opencode laptop" --models muse-glimmer-30b-heretic,granite-4.2-8b
sudo keygate add "kids tablet" --models chatterbox
sudo keygate add admin --models '*'                # every model
sudo keygate import "old key" --models '*' <<< "sk-…"   # add a key you already have

sudo keygate list                                   # id, label, models, last used
sudo keygate allow "kids tablet" 'gemma-*'          # glob patterns work
sudo keygate deny  "kids tablet" chatterbox
sudo keygate label 3 "Hermes on the NAS"
sudo keygate revoke 3                               # kept in the DB so its log entries still have a name

sudo keygate models                                 # model names llama-swap offers
sudo keygate log -n 50 [--key "opencode laptop"]    # recent requests
sudo keygate usage --days 30                        # requests and tokens per key and model
sudo keygate prune --days 90                        # trim the request log
```

`KEY` can be the id from `list`, the label, or the key's first 8 characters. Changes apply to the very next request;
nothing needs restarting.

**Keys are shown once, when created.** The database stores only a SHA-256 hash, so a copied database file doesn't
leak working keys. A lost key can't be recovered: revoke it and add a new one.

## What it allows

| Request | Rule |
|---|---|
| `POST /v1/…`, `/completion`, `/infill`, `/rerank`, `/embedding(s)` | model taken from the JSON body (or the multipart `model` field) and checked |
| `/upstream/<model>/…` (e.g. ComfyUI's API) | model taken from the path and checked |
| `GET /v1/models` | answered, but lists only the models this key may use |
| `GET /health` | no key needed |
| anything else (llama-swap's UI, `/logs`, `/running`, `/unload`, `/api/…`) | 404 — use `http://127.0.0.1:8081` on the server |

Keys are accepted as `Authorization: Bearer <key>` or `X-Api-Key: <key>`. Wrong or revoked key → 401, model not
allowed → 403, both with an OpenAI-style JSON error. Failed attempts are logged too.

## The log

Table `requests` in `/var/lib/keygate/keygate.db`: time (UTC), key, client IP, method, path, model, status,
duration, bytes in/out, prompt and output tokens, and a note (denial reason, client disconnected, upstream error).
Prompts and replies are **not** stored. Token counts come from the reply's `usage` block, or for streamed replies
from llama-server's closing `timings` block.

```bash
sudo sqlite3 /var/lib/keygate/keygate.db 'SELECT ts, model, status FROM requests ORDER BY id DESC LIMIT 5'
```

## Install

```bash
sudo keygate/install.sh
```

It creates a `keygate` system user, installs `/usr/local/bin/keygate` and the systemd unit, generates an internal
key for llama-swap, **moves the keys already in llama-swap's `apiKeys:` into keygate** (allowed every model, so
existing clients keep working), and moves llama-swap to `127.0.0.1:8081` with a systemd drop-in
(`/etc/systemd/system/llama-swap.service.d/keygate.conf`). The llama-swap config is backed up first. Safe to re-run;
re-running also updates the installed program after a `git pull`.

Settings are in `/etc/keygate/keygate.env`:

| Variable | Default | |
|---|---|---|
| `KEYGATE_LISTEN` | `0.0.0.0:8080` | where clients connect |
| `KEYGATE_UPSTREAM` | `127.0.0.1:8081` | llama-swap |
| `KEYGATE_UPSTREAM_KEY` | generated | llama-swap's only `apiKey` |
| `KEYGATE_TIMEOUT` | `3600` | seconds to wait on a silent upstream (model loads, long reasoning) |
| `KEYGATE_DB` | `/var/lib/keygate/keygate.db` | |

To undo: `sudo systemctl disable --now keygate`, delete the llama-swap drop-in, restore the
`config.yaml.bak-pre-keygate-*` backup, `sudo systemctl daemon-reload && sudo systemctl restart llama-swap`.

## Limits

- Not a firewall for things that don't go through it: ComfyUI's web UI on `:8188` is reached directly.
- Plain HTTP. Fine on a home LAN; put a TLS reverse proxy in front if keys cross untrusted networks.
- No rate limits or budgets; `keygate usage` shows who used what.
