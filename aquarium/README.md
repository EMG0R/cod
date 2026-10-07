# Aquarium

An aquarium is a network of agents across machines. One machine runs the hub.
Every machine, including the hub's, is a node with a name. Nodes send messages
to each other through the hub. A message addressed to a node can be typed into
a tmux session on that node, so it arrives inside a running agent's context
instead of sitting in a file.

Files:

- `hub.py` - the hub. Python standard library only. Append-only JSONL store.
- `cod` - the client. Copy it to any node.
- `systemd/cod-hub.service` - user unit template.
- `examples/` - runnable examples.

## Auth model

Tokens are `base64url("<expiry>:<hmac_sha256(secret, expiry)>")`. The hub
validates by recomputing the HMAC. There is no account system.

- On first run the hub creates a random secret at `COD_HUB_SECRET_FILE`
  (default `~/.cod/hub_secret`, mode 600).
- `cod token` on the hub machine mints a token from that secret.
  `cod token --ttl SECONDS` sets lifetime (default one year).
- Give a node a token by setting `COD_BUS_TOKEN` on it. A token is a bearer
  credential: anyone holding it can read and send. Treat it like a password.
- Optional adapter: if `COD_AUTH_ADAPTER_CONFIG` points at a JSON file with a
  `token_secret` key, tokens signed with that secret are also accepted. Unset
  by default.
- Rotating: delete the secret file and restart the hub. All old tokens stop
  working.
- The hub speaks plain HTTP. Across untrusted networks put it behind a VPN or
  a TLS-terminating proxy.

## API

All endpoints except health need `Authorization: Bearer <token>` (or `?token=`).

    POST /cod/bus   {"from":"a","to":"b","body":"text"}  -> {"ok":true,"id":N,"ts":...}
    GET  /cod/bus?since=N&to=b&wait=25                   -> {"messages":[...],"last":N}
    GET  /cod/bus/health                                 -> {"ok":true,"node":"..."}   (no auth)

- `to` on POST: a node name, or `*` / `all` for broadcast (default `*`).
- `since`: return messages with id greater than N. Ids are line numbers in the store.
- `to` on GET: return messages addressed to that node plus broadcasts.
- `wait`: long-poll up to that many seconds (max 50). An empty list on timeout.
- Body limit 64 KiB. Bad token returns 401.

## Hub configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `COD_BUS_BIND` | `127.0.0.1` | Interface to listen on. Widening is your decision. |
| `COD_BUS_PORT` | `8798` | Port. |
| `COD_BUS_NODE` | hostname | This hub machine's node name. |
| `COD_BUS_TMUX` | `claude` | tmux session that receives messages addressed to the hub's own node. |
| `COD_HUB_STORE` | `~/.cod/messages.jsonl` | Message store. |
| `COD_HUB_SECRET_FILE` | `~/.cod/hub_secret` | Hub secret, created on first run. |
| `COD_AUTH_ADAPTER_CONFIG` | unset | Optional extra JSON secret file (`token_secret`). |

## Client configuration

Resolved in order: flags, environment, `~/.cod-bus.conf` (lines of `KEY=value`).

| Variable | Default | Meaning |
|---|---|---|
| `COD_BUS_URL` | `http://127.0.0.1:8798` | Hub URL. |
| `COD_BUS_TOKEN` | empty | Bearer token. |
| `COD_BUS_NODE` | hostname | This node's name. |
| `COD_BUS_DELIVER` | empty | `tmux:<session>`: type arriving messages into that session. |
| `COD_BUS_STATE` | `~/.cod-bus.since` | File that remembers the last message id read. |
| `COD_HUB_SECRET_FILE` | `~/.cod/hub_secret` | Used by `cod token`. |
| `COD_AUTH_ADAPTER_CONFIG` | unset | If set, `cod token` signs with that secret instead. |
| `COD_MESH_DIR` | unset | Enables optional `cod nodes/ssh/scp` (see below). |

## Commands

    cod token [--ttl SECONDS]        mint a token (run on the hub machine)
    cod health                       hub liveness
    cod send <to> <text...>          send
    cod recv [--since N] [--wait S] [--deliver tmux:S]   read once
    cod listen [--deliver tmux:S]    long-poll forever, print as they arrive

`recv` and `listen` remember their position in `COD_BUS_STATE`. Two agents on
the same machine need distinct `COD_BUS_NODE` and `COD_BUS_STATE` values.

Optional: if `COD_MESH_DIR` names a directory with one sub-directory per node
(containing `mesh.pub` once keyed), `cod nodes`, `cod ssh <node>` and
`cod scp` check the node name and then call plain `ssh`/`scp`, using the node
name as the ssh host alias. Unset, these commands print a notice and exit.

## Delivery

`send-keys -l` types the text literally into the tmux session, then a separate
`Enter` submits it. The line looks like `[COD bus] from <node>: <body>`.
Whitespace is collapsed and the line is capped at 4000 characters. A node's
own broadcasts are not typed back into its own session. Delivery failure never
fails a send: the message is already stored.

The hub delivers for its own node. Every other node delivers to itself with
`cod listen --deliver tmux:<session>`.

## Limits

No message encryption, no per-node permissions (a token reads everything), no
retention policy (the store only grows), single hub. Rotate the secret to
revoke.
