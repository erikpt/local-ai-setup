#!/usr/bin/env python3
"""keygate — API keys with per-model permissions, in front of llama-swap.

Python standard library + SQLite only. Clients talk to keygate (default :8080) with their own key; keygate checks
that the key may use the requested model, forwards the request to llama-swap (default 127.0.0.1:8081) with an
internal key, streams the reply back, and logs the request to SQLite.

  keygate serve                                   run the proxy (systemd does this)
  keygate add LABEL --models a,b | '*'            create a key; printed once, only its hash is stored
  keygate import LABEL --models ...               add an existing key, read from stdin
  keygate list                                    keys, their models, last use
  keygate allow KEY MODEL...                      let a key use more models ('*' and globs like 'gemma-*' work)
  keygate deny KEY MODEL...                       take models away
  keygate label KEY NEW-LABEL                     rename
  keygate revoke KEY                              disable a key (kept so its log entries stay readable)
  keygate models                                  models llama-swap offers
  keygate log [-n 30] [--key KEY]                 recent requests
  keygate usage [--days 7]                        requests and tokens per key and model
  keygate prune [--days 90]                       delete old log entries

KEY is the id from `list`, the label, or the key's first 8 characters (e.g. sk-5e30a).
Changes take effect immediately; nothing needs a restart. Run the CLI with sudo.
"""
import argparse, datetime, fnmatch, hashlib, http.client, http.server, json, os, pwd, re, secrets, sqlite3, sys, time
import urllib.parse

ENV_FILE = "/etc/keygate/keygate.env"


def load_env_file():
    # The service gets these from systemd; the CLI (run with sudo) reads the same file.
    try:
        with open(ENV_FILE) as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep and not k.startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip())
    except (FileNotFoundError, PermissionError):
        pass


load_env_file()
DB = os.environ.get("KEYGATE_DB", "/var/lib/keygate/keygate.db")
LISTEN = os.environ.get("KEYGATE_LISTEN", "0.0.0.0:8080")
UPSTREAM = os.environ.get("KEYGATE_UPSTREAM", "127.0.0.1:8081")
UPSTREAM_KEY = os.environ.get("KEYGATE_UPSTREAM_KEY", "")
TIMEOUT = float(os.environ.get("KEYGATE_TIMEOUT", "3600"))  # model loads + long reasoning can be silent for minutes
MAX_BODY = 64 << 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS keys(
  id INTEGER PRIMARY KEY, hash TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL, label TEXT NOT NULL,
  created TEXT NOT NULL, revoked TEXT, last_used TEXT);
CREATE TABLE IF NOT EXISTS permissions(
  key_id INTEGER NOT NULL REFERENCES keys(id), model TEXT NOT NULL, PRIMARY KEY(key_id, model));
CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, key_id INTEGER, client TEXT, method TEXT, path TEXT, model TEXT,
  status INTEGER, ms INTEGER, bytes_in INTEGER, bytes_out INTEGER, prompt_tokens INTEGER,
  completion_tokens INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS requests_key ON requests(key_id, ts);
"""

# POST endpoints that run a model (llama-swap routes them by the "model" field). Everything else — llama-swap's
# UI, logs, /running, /unload, /api/* — is not reachable through keygate.
MODEL_POSTS = ("/v1/", "/completion", "/infill", "/rerank", "/reranking", "/embedding", "/embeddings")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
       "transfer-encoding", "upgrade", "content-length", "host", "authorization", "x-api-key"}


def now():  # stored in UTC so comparisons work across DST changes; shown in local time
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ago(days):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def local(ts, fmt="%m-%d %H:%M:%S"):
    return datetime.datetime.fromisoformat(ts).astimezone().strftime(fmt) if ts else None


def connect():
    con = sqlite3.connect(DB, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def allowed(con, key_id, model):
    pats = [r["model"] for r in con.execute("SELECT model FROM permissions WHERE key_id=?", (key_id,))]
    return any(fnmatch.fnmatchcase(model, p) for p in pats)


def upstream_conn():
    host, _, port = UPSTREAM.rpartition(":")
    return http.client.HTTPConnection(host, int(port), timeout=TIMEOUT)


def upstream_headers():
    return {"Authorization": f"Bearer {UPSTREAM_KEY}"} if UPSTREAM_KEY else {}


def upstream_models():
    c = upstream_conn()
    c.request("GET", "/v1/models", headers=upstream_headers())
    r = c.getresponse()
    body = r.read()
    if r.status != 200:
        raise RuntimeError(f"llama-swap /v1/models returned {r.status}: {body[:200]!r}")
    return json.loads(body)


# ---------------------------------------------------------------------------------------------------- the proxy

class Gate(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "keygate"
    sys_version = ""

    def log_message(self, fmt, *args):  # requests go to SQLite; only errors go to the journal
        pass

    def do_GET(self): self.handle_any()
    def do_POST(self): self.handle_any()
    def do_PUT(self): self.handle_any()
    def do_DELETE(self): self.handle_any()
    def do_PATCH(self): self.handle_any()
    def do_HEAD(self): self.handle_any()

    def do_OPTIONS(self):  # CORS preflight carries no key; answer it so browser clients work
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Api-Key")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def reply(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        self.rec["bytes_out"] += len(data)
        self.rec["status"] = status

    def error(self, status, msg, kind="invalid_request_error"):
        self.rec["note"] = msg
        self.reply(status, {"error": {"message": msg, "type": kind, "code": status}})

    def handle_any(self):
        self.close_connection = True
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            data = b"OK"
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            return
        t0 = time.monotonic()
        self.rec = {"ts": now(), "key_id": None, "client": self.client_address[0], "method": self.command,
                    "path": self.path[:300], "model": None, "status": None, "bytes_in": 0, "bytes_out": 0,
                    "prompt_tokens": None, "completion_tokens": None, "note": None}
        con = connect()
        try:
            self.route(con, path)
        except (BrokenPipeError, ConnectionResetError):
            self.rec["note"] = "client disconnected"
            self.rec["status"] = self.rec["status"] or 499
        except Exception as e:  # upstream down, timeout, bad JSON ...
            print(f"keygate: {self.command} {self.path}: {e!r}", file=sys.stderr, flush=True)
            if self.rec["status"] is None:
                try:
                    self.error(502, f"upstream error: {e}", "upstream_error")
                except OSError:
                    pass
            else:
                self.rec["note"] = f"stream aborted: {e}"
        finally:
            self.rec["ms"] = int((time.monotonic() - t0) * 1000)
            try:
                con.execute("INSERT INTO requests(ts,key_id,client,method,path,model,status,ms,bytes_in,bytes_out,"
                            "prompt_tokens,completion_tokens,note) VALUES(:ts,:key_id,:client,:method,:path,:model,"
                            ":status,:ms,:bytes_in,:bytes_out,:prompt_tokens,:completion_tokens,:note)", self.rec)
            except sqlite3.Error as e:
                print(f"keygate: log write failed: {e}", file=sys.stderr, flush=True)
            con.close()

    def route(self, con, path):
        # 1. who is calling
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("X-Api-Key", "").strip()
        row = con.execute("SELECT id, revoked FROM keys WHERE hash=?", (key_hash(token),)).fetchone() if token else None
        if not row or row["revoked"]:
            return self.error(401, "invalid or missing API key", "authentication_error")
        key_id = self.rec["key_id"] = row["id"]
        con.execute("UPDATE keys SET last_used=? WHERE id=?", (self.rec["ts"], key_id))

        # 2. read the body
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            return self.error(411, "chunked request bodies are not supported; send Content-Length")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.error(413, "request body too large")
        body = self.rfile.read(length) if length else None
        self.rec["bytes_in"] = length

        # 3. which model
        if self.command in ("GET", "HEAD") and path in ("/v1/models", "/models"):
            data = upstream_models()
            data["data"] = [m for m in data.get("data", []) if allowed(con, key_id, m.get("id", ""))]
            return self.reply(200, data)
        if path.startswith("/upstream/"):
            model = urllib.parse.unquote(path.split("/")[2])
        elif self.command == "POST" and path.startswith(MODEL_POSTS):
            model = self.model_from_body(body)
            if not model:
                return self.error(400, "request has no 'model'")
        else:
            return self.error(404, f"{self.command} {path} is not available through this gateway")
        self.rec["model"] = model[:200]

        # 4. may this key use it
        if not allowed(con, key_id, model):
            return self.error(403, f"this API key is not allowed to use model '{model}'", "permission_error")

        # 5. forward and stream back
        self.forward(body)

    def model_from_body(self, body):
        if not body:
            return None
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" in ctype:  # e.g. /v1/audio/transcriptions
            m = re.search(rb'name="model"\r\n(?:[^\r\n]*\r\n)*\r\n([^\r\n]+)', body)
            return m.group(1).decode(errors="replace").strip() if m else None
        try:
            obj = json.loads(body)
        except ValueError:
            return None
        return obj.get("model") if isinstance(obj, dict) and isinstance(obj.get("model"), str) else None

    def forward(self, body):
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        hdrs.update(upstream_headers())
        if body is not None:
            hdrs["Content-Length"] = str(len(body))
        up = upstream_conn()
        try:
            up.request(self.command, self.path, body=body, headers=hdrs)
            resp = up.getresponse()
            self.send_response(resp.status, resp.reason)
            self.rec["status"] = resp.status
            for k, v in resp.getheaders():
                if k.lower() not in HOP and k.lower() not in ("server", "date"):
                    self.send_header(k, v)
            clen = resp.getheader("Content-Length")
            chunked = clen is None and self.command != "HEAD"
            if clen is not None:
                self.send_header("Content-Length", clen)
            elif chunked:
                self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            tail = b""
            while self.command != "HEAD":
                chunk = resp.read1(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk) if chunked else chunk)
                self.wfile.flush()
                self.rec["bytes_out"] += len(chunk)
                tail = (tail + chunk)[-65536:]
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            # token counts: the last "usage" block (plain JSON replies, or streams with include_usage), else
            # llama-server's "timings" block, which ends every stream
            def last(name):
                hits = re.findall(rb'"%s"\s*:\s*(\d+)' % name.encode(), tail)
                return int(hits[-1]) if hits else None
            pt, ct = last("prompt_tokens"), last("completion_tokens")
            if pt is None and last("prompt_n") is not None:
                pt = last("prompt_n") + (last("cache_n") or 0)
            if ct is None:
                ct = last("predicted_n")
            self.rec["prompt_tokens"], self.rec["completion_tokens"] = pt, ct
        finally:
            up.close()  # if the client went away mid-stream, this tells llama-server to stop generating


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def serve():
    con = connect()
    con.executescript(SCHEMA)
    n = con.execute("SELECT count(*) FROM keys WHERE revoked IS NULL").fetchone()[0]
    con.close()
    host, _, port = LISTEN.rpartition(":")
    print(f"keygate: listening on {LISTEN}, upstream {UPSTREAM}, {n} active keys, db {DB}", flush=True)
    Server((host, int(port)), Gate).serve_forever()


# ---------------------------------------------------------------------------------------------------- the CLI

def as_service_user():
    # Run CLI writes as the service's user, so root never creates DB/WAL files the service can't open.
    if os.geteuid() == 0:
        try:
            pw = pwd.getpwnam("keygate")
        except KeyError:
            return
        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)


def cli_db():
    as_service_user()
    try:
        con = connect()
        con.executescript(SCHEMA)
        return con
    except sqlite3.OperationalError as e:
        sys.exit(f"can't open {DB} ({e}) — run with sudo")


def find_key(con, ref):
    rows = []
    if ref.isdigit():
        rows = con.execute("SELECT * FROM keys WHERE id=?", (int(ref),)).fetchall()
    if not rows:
        rows = con.execute("SELECT * FROM keys WHERE label=?", (ref,)).fetchall()
    if not rows and len(ref) >= 6:
        rows = con.execute("SELECT * FROM keys WHERE prefix LIKE ?", (ref[:8] + "%",)).fetchall()
    if len(rows) != 1:
        sys.exit(f"'{ref}' matches {len(rows)} keys — use the id from `keygate list`")
    return rows[0]


def split_models(values):
    out = []
    for v in values:
        out += [m.strip() for m in v.split(",") if m.strip()]
    return out


def check_models(models):
    try:
        known = {m["id"] for m in upstream_models().get("data", [])}
    except Exception as e:
        print(f"(couldn't ask llama-swap for its model list: {e})")
        return
    for m in models:
        if not any(fnmatch.fnmatchcase(k, m) for k in known):
            print(f"warning: '{m}' doesn't match any model llama-swap has right now")


def insert_key(con, key, label, models):
    if con.execute("SELECT 1 FROM keys WHERE hash=?", (key_hash(key),)).fetchone():
        sys.exit("that key is already in keygate")
    cur = con.execute("INSERT INTO keys(hash,prefix,label,created) VALUES(?,?,?,?)",
                      (key_hash(key), key[:8], label, now()))
    con.executemany("INSERT OR IGNORE INTO permissions VALUES(?,?)", [(cur.lastrowid, m) for m in models])
    return cur.lastrowid


def models_of(con, key_id):
    return ", ".join(r[0] for r in con.execute("SELECT model FROM permissions WHERE key_id=? ORDER BY model", (key_id,)))


def table(rows, headers):
    rows = [[("" if c is None else str(c)) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(headers)))
    for r in rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)))


def main():
    ap = argparse.ArgumentParser(prog="keygate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    for name in ("add", "import"):
        p = sub.add_parser(name)
        p.add_argument("label")
        p.add_argument("--models", required=True, action="append", help="comma-separated; '*' for all")
    sub.add_parser("list")
    for name in ("allow", "deny"):
        p = sub.add_parser(name); p.add_argument("key"); p.add_argument("models", nargs="+")
    p = sub.add_parser("label"); p.add_argument("key"); p.add_argument("new_label")
    p = sub.add_parser("revoke"); p.add_argument("key")
    sub.add_parser("models")
    p = sub.add_parser("log"); p.add_argument("-n", type=int, default=30); p.add_argument("--key")
    p = sub.add_parser("usage"); p.add_argument("--days", type=float, default=7)
    p = sub.add_parser("prune"); p.add_argument("--days", type=float, default=90)
    a = ap.parse_args()

    if a.cmd == "serve":
        return serve()
    if a.cmd == "models":
        for m in upstream_models().get("data", []):
            print(m["id"])
        return

    con = cli_db()
    if a.cmd in ("add", "import"):
        models = split_models(a.models)
        if a.cmd == "add":
            key = "sk-" + secrets.token_hex(24)
        else:
            key = sys.stdin.readline().strip()
            if not key or " " in key:
                sys.exit("paste the key on stdin, e.g.  echo 'sk-...' | sudo keygate import LABEL --models '*'")
        check_models(models)
        kid = insert_key(con, key, a.label, models)
        print(f"key {kid} '{a.label}' may use: {', '.join(models)}")
        if a.cmd == "add":
            print(f"\n{key}\n\nThis is the only time the key is shown; keygate stores just a hash of it.")

    elif a.cmd == "list":
        rows = con.execute("SELECT * FROM keys ORDER BY id").fetchall()
        table([(r["id"], r["prefix"] + "…", r["label"], models_of(con, r["id"]) or "(none)",
                local(r["last_used"], "%Y-%m-%d %H:%M") or "never", "REVOKED" if r["revoked"] else "active")
               for r in rows], ["id", "key", "label", "models", "last used", "status"])

    elif a.cmd in ("allow", "deny"):
        k = find_key(con, a.key)
        models = split_models(a.models)
        if a.cmd == "allow":
            check_models(models)
            con.executemany("INSERT OR IGNORE INTO permissions VALUES(?,?)", [(k["id"], m) for m in models])
        else:
            for m in models:
                if con.execute("DELETE FROM permissions WHERE key_id=? AND model=?", (k["id"], m)).rowcount == 0:
                    print(f"note: key {k['id']} had no permission named exactly '{m}'")
        print(f"key {k['id']} '{k['label']}' may use: {models_of(con, k['id']) or '(nothing)'}")

    elif a.cmd == "label":
        k = find_key(con, a.key)
        con.execute("UPDATE keys SET label=? WHERE id=?", (a.new_label, k["id"]))
        print(f"key {k['id']} is now '{a.new_label}'")

    elif a.cmd == "revoke":
        k = find_key(con, a.key)
        con.execute("UPDATE keys SET revoked=? WHERE id=?", (now(), k["id"]))
        print(f"key {k['id']} '{k['label']}' revoked — requests with it now get 401")

    elif a.cmd == "log":
        q, args = "SELECT r.*, k.label FROM requests r LEFT JOIN keys k ON k.id=r.key_id", []
        if a.key:
            q += " WHERE r.key_id=?"; args.append(find_key(con, a.key)["id"])
        rows = con.execute(q + " ORDER BY r.id DESC LIMIT ?", (*args, a.n)).fetchall()[::-1]
        table([(local(r["ts"]), r["label"] or "-", r["client"], r["model"] or r["path"][:40],
                r["status"], f'{r["ms"] / 1000:.1f}s', r["prompt_tokens"], r["completion_tokens"], r["note"])
               for r in rows], ["time", "key", "client", "model / path", "status", "took", "in tok", "out tok", "note"])

    elif a.cmd == "usage":
        since = ago(a.days)
        rows = con.execute("""SELECT coalesce(k.label,'(bad key)') label, coalesce(r.model,'-') model, count(*) n,
                              sum(r.status>=400) errors, sum(r.prompt_tokens) pt, sum(r.completion_tokens) ct
                              FROM requests r LEFT JOIN keys k ON k.id=r.key_id WHERE r.ts>=?
                              GROUP BY 1,2 ORDER BY 1, n DESC""", (since,)).fetchall()
        print(f"last {a.days:g} days")
        table([tuple(r) for r in rows], ["key", "model", "requests", "errors", "prompt tok", "output tok"])

    elif a.cmd == "prune":
        n = con.execute("DELETE FROM requests WHERE ts<?", (ago(a.days),)).rowcount
        con.execute("VACUUM")
        print(f"deleted {n} log entries older than {a.days:g} days")


if __name__ == "__main__":
    main()
