# 02 - two machines

A second machine joins the aquarium over a LAN or VPN. Steps only: this needs
two machines, so there is no single-command script.

Machine A (hub), address `HUB_IP`:

    cd aquarium
    COD_BUS_BIND=0.0.0.0 python3 hub.py &     # listen beyond loopback
    ./cod token                                # prints a token; copy it

`0.0.0.0` listens on every interface. Prefer binding to the one interface
your LAN or VPN uses (`COD_BUS_BIND=<that address>`), and do not expose the
port to the internet; the hub speaks plain HTTP.

Machine B (joins):

    # copy the single file `cod` to machine B, then:
    export COD_BUS_URL=http://HUB_IP:8798
    export COD_BUS_TOKEN=<token from machine A>
    export COD_BUS_NODE=machine-b
    ./cod health
    # {"ok": true, "node": "<machine A hostname>"}

Talk:

    # on B
    ./cod send machine-a "joined"
    # on A
    COD_BUS_NODE=machine-a ./cod recv
    # [12:00:00] machine-b -> machine-a: joined

To keep settings, write them to `~/.cod-bus.conf` on B as `KEY=value` lines
(`COD_BUS_URL=...`, `COD_BUS_TOKEN=...`, `COD_BUS_NODE=...`).

If `cod health` fails: check the hub is bound to a reachable address, the port
is open in the firewall, and `COD_BUS_URL` has no typo. A 401 means the token
is wrong or minted from a different secret.

You can rehearse this on one machine by using `http://127.0.0.1:8798` as the
URL and a different `COD_BUS_NODE` and `COD_BUS_STATE`.
