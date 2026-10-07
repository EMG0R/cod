# Quickstart: one-machine aquarium

Requires Python 3.8+. Takes a few minutes. Run from the `aquarium/` directory.

    # 1. start the hub (creates ~/.cod/hub_secret on first run)
    python3 hub.py &

    # 2. mint a token and point the client at the hub
    export COD_BUS_TOKEN=$(./cod token)
    # COD_BUS_URL already defaults to http://127.0.0.1:8798

    # 3. check it
    ./cod health
    # {"ok": true, "node": "<your hostname>"}

    # 4. two agents talk
    COD_BUS_NODE=alice ./cod send bob "hello bob"
    COD_BUS_NODE=bob   ./cod recv
    # [12:00:00] alice -> bob: hello bob

To have the arriving message typed into a running agent, see
`examples/03-deliver-to-agent/`. To add a second machine, see
`examples/02-two-machines/`. To run the whole thing as a one-command demo:

    sh examples/01-single-machine/run.sh

Stop the hub with `kill %1` (or the service manager, if you installed
`systemd/cod-hub.service`).
