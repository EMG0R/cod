# 01 - single machine

A hub and two agents (alice and bob) on one laptop, talking.

    sh run.sh

It starts a hub on port 8797 (override with `COD_DEMO_PORT`) with a temporary
store and a fresh secret, then removes everything on exit. Expected output
(times differ):

    {"ok": true, "node": "hub"}
    --- alice sends
    sent id=1
    --- bob receives
    [12:00:00] alice -> bob: hello bob
    --- bob replies, alice receives
    sent id=2
    [12:00:00] bob -> alice: hello alice
    --- bob has nothing new
    --- done

The same steps by hand are in `../../QUICKSTART.md`. Each agent needs its own
`COD_BUS_NODE` and `COD_BUS_STATE`, because the state file records what that
node has already read.
