#!/bin/sh
# Message -> tmux session. The session runs `cat` as a stand-in for an agent:
# whatever is typed into it shows up on its screen exactly as it would in an
# agent's input. Needs tmux. Run: sh run.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
AQ=$HERE/../..
D=$(mktemp -d)
PORT=${COD_DEMO_PORT:-8797}
SESS=cod-demo-agent
cleanup() { kill $HUB $LISTEN 2>/dev/null; tmux kill-session -t $SESS 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT

export COD_HUB_STORE=$D/messages.jsonl COD_HUB_SECRET_FILE=$D/secret
export COD_BUS_PORT=$PORT COD_BUS_NODE=hub COD_BUS_TMUX=none
python3 "$AQ/hub.py" >"$D/hub.log" 2>&1 &
HUB=$!
sleep 1
export COD_BUS_URL=http://127.0.0.1:$PORT
export COD_BUS_TOKEN=$("$AQ/cod" token)

# the "agent": a session that just echoes its input
tmux new-session -d -s $SESS -x 120 -y 20 cat

# the node's listener: delivers arriving messages into that session
COD_BUS_NODE=worker COD_BUS_STATE=$D/worker.since \
  "$AQ/cod" listen --deliver tmux:$SESS >"$D/listen.log" 2>&1 &
LISTEN=$!
sleep 1

# someone else sends to the worker
COD_BUS_NODE=planner COD_BUS_STATE=$D/planner.since \
  "$AQ/cod" send worker "run the tests and report back"
sleep 2

echo "--- what is now on the agent's screen"
tmux capture-pane -p -t $SESS | sed '/^$/d'
