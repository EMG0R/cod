# 03 - deliver to an agent

A message log is not an agent network. What makes this one is that an
arriving message is typed into a tmux session, so a running agent (a CLI
coding agent, a REPL, anything reading a terminal) receives it as input, in
its live context, with no polling by the agent.

    sh run.sh

`run.sh` starts a hub, creates a tmux session named `cod-demo-agent` running
`cat` as a stand-in agent, starts a listener with
`cod listen --deliver tmux:cod-demo-agent`, then a second node sends it a
message. Expected output:

    sent id=1
    --- what is now on the agent's screen
    [COD bus] from planner: run the tests and report back
    [COD bus] from planner: run the tests and report back

The line appears twice because the terminal echoes the typed input and then
`cat` prints it. A real agent shows it once, as a prompt it then acts on.

## With a real agent

1. Start your agent inside tmux: `tmux new -s agent` then run it.
2. On that machine, in another shell:

        export COD_BUS_URL=... COD_BUS_TOKEN=... COD_BUS_NODE=my-node
        cod listen --deliver tmux:agent

   Or set `COD_BUS_DELIVER=tmux:agent` once and run `cod listen`.
3. From any node: `cod send my-node "check the build"`.

The text arrives as `[COD bus] from <node>: check the build`, followed by
Enter. Tell your agent in its instructions what that prefix means and how to
reply (`cod send <node> <text>`).

On the hub machine itself, set `COD_BUS_TMUX=<session>` for the hub and it
delivers messages addressed to its own node directly; no listener needed.

How it works: `tmux send-keys -l` types the text literally (no key-name
interpretation), then a separate `Enter` submits it. Whitespace is collapsed
and the line is capped at 4000 characters. A message from a node is never
typed back into that same node's own session. If the session does not exist,
delivery is skipped; the message stays on the hub for `cod recv`.
