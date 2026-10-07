#!/bin/sh
# Hub plus two agents (alice, bob) on one machine. Uses a throwaway directory
# and port, so it never touches ~/.cod. Run: sh run.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
AQ=$HERE/../..
D=$(mktemp -d)
PORT=${COD_DEMO_PORT:-8797}
trap 'kill $HUB 2>/dev/null; rm -rf "$D"' EXIT

export COD_HUB_STORE=$D/messages.jsonl COD_HUB_SECRET_FILE=$D/secret
export COD_BUS_PORT=$PORT COD_BUS_NODE=hub COD_BUS_TMUX=none
python3 "$AQ/hub.py" >"$D/hub.log" 2>&1 &
HUB=$!
sleep 1

export COD_BUS_URL=http://127.0.0.1:$PORT
export COD_BUS_TOKEN=$("$AQ/cod" token)
"$AQ/cod" health

alice() { COD_BUS_NODE=alice COD_BUS_STATE=$D/alice.since "$AQ/cod" "$@"; }
bob()   { COD_BUS_NODE=bob   COD_BUS_STATE=$D/bob.since   "$AQ/cod" "$@"; }

echo "--- alice sends"
alice send bob "hello bob"
echo "--- bob receives"
bob recv
echo "--- bob replies, alice receives"
bob send alice "hello alice"
alice recv
echo "--- bob has nothing new"
bob recv
echo "--- done"
