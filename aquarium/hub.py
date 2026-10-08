#!/usr/bin/env python3
"""cod-bus hub — node-to-node messaging, hub-mediated.

Auth, standalone by default:
  On first run this generates a random secret at COD_HUB_SECRET_FILE
  (default ~/.cod/hub_secret, mode 600) and mints/validates bearer tokens
  against it with HMAC-SHA256. No external file, no account, works on a bare
  machine with nothing else installed. Mint a token with `cod token` (see the
  client). This is the only thing you need for a brand-new aquarium.

Auth, optional external adapter:
  If COD_AUTH_ADAPTER_CONFIG points at a JSON file with a "token_secret" key,
  that secret is ALSO accepted (in addition to the standalone one, not instead
  of it) -- so an existing deployment that already issues tokens against some
  other secret store can point the hub at it without forcing every existing
  token to be reminted. This is how you bolt the hub onto something you
  already run (your own auth service, a reverse proxy, whatever already holds
  a shared secret) without hard-wiring that system's paths into this one.
  Leave COD_AUTH_ADAPTER_CONFIG unset and nothing changes from the default.

Why stdlib and no venv: a message bus is "append a line, read lines after N".
Nothing here is worth a dependency tree.

Bind: COD_BUS_BIND, default 127.0.0.1 -- loopback only until you choose to
widen it. Widening to 0.0.0.0 or a specific interface is a deliberate decision
for whoever runs this hub, never a default.

API (all auth'd with `Authorization: Bearer <token>` or ?token=):
  POST /cod/bus            {"from":"node-a","to":"node-b","body":"..."}
                           -> {"ok":true,"id":N,"ts":...}
  GET  /cod/bus?since=N&to=node-b&wait=25
                           -> {"messages":[...],"last":N}   long-polls up to
                              `wait` seconds for something new; returns [] on
                              timeout so the caller just asks again.
  GET  /cod/bus/health     no auth. liveness only, says nothing else.

Delivery: a message addressed to THIS hub's own node (COD_BUS_NODE, default
the machine hostname) is also typed into a local tmux session (COD_BUS_TMUX,
default "claude"), so it lands in a running agent's context instead of
sitting in a file nobody reads. Every other node delivers to itself the same
way, client-side -- see `cod recv --deliver`.
"""
import base64, hashlib, hmac, json, os, re, secrets, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOME = os.path.expanduser("~")
STORE = os.environ.get("COD_HUB_STORE", os.path.join(HOME, ".cod", "messages.jsonl"))
SECRET_FILE = os.environ.get("COD_HUB_SECRET_FILE", os.path.join(HOME, ".cod", "hub_secret"))
ADAPTER_CONFIG = os.environ.get("COD_AUTH_ADAPTER_CONFIG", "")
BIND = os.environ.get("COD_BUS_BIND", "127.0.0.1")
PORT = int(os.environ.get("COD_BUS_PORT", "8798"))
SELF_NODE = os.environ.get("COD_BUS_NODE") or socket.gethostname()
TMUX_SESSION = os.environ.get("COD_BUS_TMUX", "claude")
MAX_BODY = 64 * 1024

_lock = threading.Lock()
_new = threading.Condition(_lock)
_count = 0


def _standalone_secret():
    """Generate-once, read-forever hub secret. No external dependency."""
    path = SECRET_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    with open(path) as f:
        return f.read().strip()


def _adapter_secret():
    """Optional extra secret from an externally-managed config file.

    The path is entirely env-driven and has no personal default -- if
    COD_AUTH_ADAPTER_CONFIG is unset, this is a no-op and the standalone
    secret is the only one in play.
    """
    if not ADAPTER_CONFIG:
        return None
    try:
        with open(ADAPTER_CONFIG) as f:
            return json.load(f).get("token_secret")
    except Exception:
        return None


def _secrets():
    secs = [_standalone_secret()]
    extra = _adapter_secret()
    if extra:
        secs.append(extra)
    return secs


def valid_token(tok):
    """b64(exp:hmac_sha256(exp)). Accepted against any active secret."""
    if not tok:
        return False
    try:
        exp, sig = base64.urlsafe_b64decode(tok.encode()).decode().split(":", 1)
        if int(exp) <= time.time():
            return False
    except Exception:
        return False
    for secret in _secrets():
        good = hmac.new(secret.encode(), exp.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good):
            return True
    return False


def _load_count():
    global _count
    try:
        with open(STORE) as f:
            _count = sum(1 for _ in f)
    except FileNotFoundError:
        _count = 0


def _read_since(since, to=None):
    out = []
    try:
        with open(STORE) as f:
            for i, line in enumerate(f, start=1):
                if i <= since:
                    continue
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if to and m.get("to") not in (to, "*", "all"):
                    continue
                m["id"] = i
                out.append(m)
    except FileNotFoundError:
        pass
    return out


def _deliver(msg):
    """Type the message into this node's agent session.

    Without this the bus is just a file. `send-keys -l` types it literally; the
    separate Enter is what submits it. Failure here must never fail the POST --
    the message is already durably on disk either way.
    """
    if msg.get("to") not in (SELF_NODE, "*", "all"):
        return
    # Don't type our own broadcast back into our own session. `to: all`
    # legitimately matches us, so the sender check is what stops the echo.
    if msg.get("from") == SELF_NODE:
        return
    try:
        if subprocess.run(["tmux", "has-session", "-t", TMUX_SESSION],
                          capture_output=True).returncode != 0:
            return
        text = "[COD bus] from %s: %s" % (msg.get("from", "?"), msg.get("body", ""))
        text = re.sub(r"\s+", " ", text).strip()[:4000]
        subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION, "-l", text],
                       capture_output=True, timeout=5)
        time.sleep(0.25)
        subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION, "Enter"],
                       capture_output=True, timeout=5)
    except Exception:
        pass



# ---------------------------------------------------------------------------
# INBOXES, TOWN HALL, MEETINGS
#
# The flat log stays exactly as it is — 193 messages of real history, and every
# existing endpoint keeps working. This adds structure ON TOP of it.
#
# Three things the flat log could not do:
#   1. PRIVATE INBOX with read state the HUB owns. Read position used to live in
#      each node's ~/.cod-bus.since, so reimaging a node lost it and nobody
#      could tell what an agent had actually seen. Cursors now live here.
#   2. TOWN HALL as a durable ROOM, not a broadcast. `to: all` pushes a message
#      at everyone once; `to: townhall` is a place you can come back and read.
#      80 of 193 messages were already broadcast, so the room exists whether or
#      not we modelled it.
#   3. MEETINGS: a convened, topic'd thread with participants and a transcript,
#      so "we agreed X" has a record instead of living in someone's context.
# ---------------------------------------------------------------------------
TOWNHALL = "townhall"
CURSOR_DIR = os.path.join(os.path.dirname(STORE), "read")
MEET_DIR = os.path.join(os.path.dirname(STORE), "meetings")


def _cursor_path(node):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", node)[:64]
    return os.path.join(CURSOR_DIR, safe)


def get_cursor(node):
    try:
        with open(_cursor_path(node)) as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0


def set_cursor(node, upto):
    os.makedirs(CURSOR_DIR, exist_ok=True)
    tmp = _cursor_path(node) + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(int(upto)))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _cursor_path(node))


def _meet_path(mid):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", mid)[:80]
    return os.path.join(MEET_DIR, safe + ".jsonl")


def meeting_append(mid, rec):
    os.makedirs(MEET_DIR, exist_ok=True)
    with open(_meet_path(mid), "a") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()
        os.fsync(f.fileno())


def meeting_read(mid):
    out = []
    try:
        with open(_meet_path(mid)) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def meetings_list():
    try:
        names = sorted(n[:-6] for n in os.listdir(MEET_DIR) if n.endswith(".jsonl"))
    except FileNotFoundError:
        return []
    out = []
    for n in names:
        recs = meeting_read(n)
        if not recs:
            continue
        head = recs[0]
        out.append({
            "meeting": n,
            "topic": head.get("topic", ""),
            "convened_by": head.get("by", ""),
            "participants": head.get("participants", []),
            "messages": sum(1 for r in recs if r.get("kind") == "say"),
            "closed": any(r.get("kind") == "close" for r in recs),
            "ts": head.get("ts"),
        })
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cod-bus"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        try:
            self.wfile.write(b)
        except Exception:
            pass

    def _auth(self, q):
        h = self.headers.get("Authorization", "")
        tok = h[7:].strip() if h.lower().startswith("bearer ") else None
        if not tok:
            tok = (q.get("token") or [None])[0]
        if not valid_token(tok):
            self._send(401, {"error": "invalid or expired token"})
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/cod/bus/health":
            return self._send(200, {"ok": True, "node": SELF_NODE})
        # private inbox: what has THIS node not seen, by the hub's reckoning
        if u.path == "/cod/inbox":
            if not self._auth(q):
                return
            node = (q.get("node") or [None])[0]
            if not node:
                return self._send(400, {"error": "need ?node="})
            cur = get_cursor(node)
            since = int((q.get("since") or [cur])[0] or 0)
            msgs = _read_since(since, node)
            with _lock:
                last = _count
            return self._send(200, {"node": node, "cursor": cur, "last": last,
                                    "unread": len(msgs), "messages": msgs})

        # town hall: a durable room, readable by anyone, not a one-shot push
        if u.path == "/cod/townhall":
            if not self._auth(q):
                return
            since = int((q.get("since") or ["0"])[0] or 0)
            msgs = [m for m in _read_since(since)
                    if m.get("to") in (TOWNHALL, "all", "*")]
            with _lock:
                last = _count
            return self._send(200, {"room": TOWNHALL, "last": last,
                                    "count": len(msgs), "messages": msgs})

        if u.path == "/cod/meetings":
            if not self._auth(q):
                return
            return self._send(200, {"meetings": meetings_list()})

        if u.path.startswith("/cod/meeting/"):
            if not self._auth(q):
                return
            mid = u.path[len("/cod/meeting/"):]
            recs = meeting_read(mid)
            if not recs:
                return self._send(404, {"error": "no such meeting"})
            return self._send(200, {"meeting": mid, "records": recs})

        if u.path != "/cod/bus":
            return self._send(404, {"error": "not found"})
        if not self._auth(q):
            return
        since = int((q.get("since") or ["0"])[0] or 0)
        to = (q.get("to") or [None])[0]
        wait = max(0, min(50, int((q.get("wait") or ["0"])[0] or 0)))
        msgs = _read_since(since, to)
        if not msgs and wait:
            deadline = time.time() + wait
            with _new:
                while not msgs and time.time() < deadline:
                    _new.wait(timeout=min(2.0, max(0.1, deadline - time.time())))
                    msgs = _read_since(since, to)
        with _lock:
            last = _count
        return self._send(200, {"messages": msgs, "last": last})

    def do_POST(self):
        global _count
        u = urlparse(self.path)
        if u.path in ("/cod/inbox/ack", "/cod/meeting/convene",
                      "/cod/meeting/say", "/cod/meeting/close"):
            if not self._auth(parse_qs(u.query)):
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_BODY:
                return self._send(400, {"error": "bad body length"})
            try:
                d = json.loads(self.rfile.read(n).decode())
            except Exception:
                return self._send(400, {"error": "bad json"})
            if not isinstance(d, dict):
                return self._send(400, {"error": "need an object"})

            if u.path == "/cod/inbox/ack":
                node = d.get("node"); upto = d.get("up_to")
                if not node or upto is None:
                    return self._send(400, {"error": "need {node, up_to}"})
                set_cursor(node, upto)
                return self._send(200, {"ok": True, "node": node,
                                        "cursor": get_cursor(node)})

            if u.path == "/cod/meeting/convene":
                topic = (d.get("topic") or "").strip()
                by = d.get("by") or "unknown"
                parts = d.get("participants") or []
                if not topic:
                    return self._send(400, {"error": "need {topic}"})
                mid = time.strftime("%Y%m%d-%H%M%S") + "-" + \
                      re.sub(r"[^a-z0-9]+", "-", topic.lower())[:40].strip("-")
                meeting_append(mid, {"kind": "convene", "topic": topic, "by": by,
                                     "participants": parts, "ts": time.time()})
                return self._send(200, {"ok": True, "meeting": mid, "topic": topic})

            if u.path == "/cod/meeting/say":
                mid = d.get("meeting"); body = d.get("body")
                if not mid or not body:
                    return self._send(400, {"error": "need {meeting, body}"})
                recs = meeting_read(mid)
                if not recs:
                    return self._send(404, {"error": "no such meeting"})
                if any(r.get("kind") == "close" for r in recs):
                    return self._send(409, {"error": "meeting is closed"})
                meeting_append(mid, {"kind": "say", "from": d.get("from") or "unknown",
                                     "body": str(body)[:MAX_BODY], "ts": time.time()})
                return self._send(200, {"ok": True, "meeting": mid})

            if u.path == "/cod/meeting/close":
                mid = d.get("meeting")
                recs = meeting_read(mid) if mid else []
                if not recs:
                    return self._send(404, {"error": "no such meeting"})
                if any(r.get("kind") == "close" for r in recs):
                    return self._send(409, {"error": "already closed"})
                meeting_append(mid, {"kind": "close", "by": d.get("by") or "unknown",
                                     "summary": str(d.get("summary") or "")[:MAX_BODY],
                                     "ts": time.time()})
                return self._send(200, {"ok": True, "meeting": mid, "closed": True})

        if u.path != "/cod/bus":
            return self._send(404, {"error": "not found"})
        if not self._auth(parse_qs(u.query)):
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._send(400, {"error": "bad body length"})
        try:
            data = json.loads(self.rfile.read(n).decode())
        except Exception:
            return self._send(400, {"error": "bad json"})
        if not isinstance(data, dict) or not data.get("body"):
            return self._send(400, {"error": "need {from,to,body}"})
        msg = {
            "from": str(data.get("from") or "unknown")[:64],
            "to": str(data.get("to") or "*")[:64],
            "body": str(data["body"])[:MAX_BODY],
            "ts": time.time(),
        }
        with _new:
            with open(STORE, "a") as f:
                f.write(json.dumps(msg) + "\n")
                f.flush()
                os.fsync(f.fileno())
            _count += 1
            mid = _count
            _new.notify_all()
        threading.Thread(target=_deliver, args=(msg,), daemon=True).start()
        return self._send(200, {"ok": True, "id": mid, "ts": msg["ts"]})


if __name__ == "__main__":
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    _standalone_secret()  # ensure it exists before anyone tries `cod token`
    _load_count()
    srv = ThreadingHTTPServer((BIND, PORT), H)
    srv.daemon_threads = True
    print("cod-bus on %s:%d as %s (%d messages)" % (BIND, PORT, SELF_NODE, _count), flush=True)
    srv.serve_forever()
