# COD agents — an agent per Pi that survives a reboot with its context

Agents belong to COD, not to the audio OS. This is the per-node agent layer:
one service that brings every registered agent back after a reboot, resumed,
with no human typing anything.

## The three pieces

| file | what it does |
|---|---|
| `claude-persist` | starts/resumes an agent in tmux; `start-all`/`boot` bring back every known agent |
| `systemd/cod-tmux.service` | **owns the tmux server** |
| `systemd/cod-agents.service` | calls `claude-persist start-all` at boot |
| `systemd/claude-persist-snapshot.{service,timer}` | every 2 min, records the sessions that are actually live |

## Install

    install -m 755 claude-persist ~/.local/bin/claude-persist
    install -m 644 systemd/*.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable cod-tmux.service cod-agents.service
    systemctl --user enable --now claude-persist-snapshot.timer
    loginctl enable-linger "$USER"

Linger matters: without it the user manager stops at logout and every agent
dies with it.

## The registry (what exists)

`claude-persist snapshot` reads `~/.claude/sessions/*.json`, keeps interactive
sessions whose pid is alive, and records each as `~/.claude-persist/up/<name>`
(`session-id<TAB>cwd<TAB>title`; name = its tmux session, else `claude-<sid8>`).
So a session a human started by hand is brought back too, not just agents
claude-persist launched. `start-all` resumes the union of the registry and the
`*.sid` files. `snapshot --add-only` never drops entries. An entry is only
dropped when it is neither live nor in a running tmux session, so a snapshot
that fires right after boot cannot empty the registry.

Opening prompts are per node and never shipped: `~/.claude-persist/<name>.bootprompt`,
`<name>.resumeprompt`, or node-wide `bootprompt` / `resumeprompt`.

## How resume works

Each agent has a pinned session id in `~/.claude-persist/<name>.sid`. On start,
if that session's transcript exists it is **resumed**; otherwise a new session
is created *pinned to that same id*, so it resumes next time. Nothing is keyed
to a hardcoded session name — a node may run several agents and a reboot must
bring back whatever was registered.

A genuinely fresh agent is handed an opening prompt. This matters more than it
looks: an agent that wakes with no context and no instruction sits at a prompt
forever. That happened — one sat idle for 7.7 hours because writing a handoff
does not make anyone read it.

## Why the tmux server gets its own unit

There is one tmux server per socket and every session lives inside it, so its
cgroup is decided by whichever unit started it first. If that is the resume
unit, then stopping, restarting or **renaming** that unit kills every agent as
collateral damage. That cost two outages in one day before it was understood.

`cod-tmux.service` owns the server; `cod-agents.service` only ever sends
`new-session` to a server that is already independent of it.

Neither unit has an `ExecStop`, deliberately. An agent-resume service must not
be able to stop an agent. The first outage was exactly that: a superseded unit
went inactive and its `ExecStop` reaped the live agent.

## Test it, don't trust it

    systemctl --user restart cod-agents.service
    pgrep -af 'claude --rc'     # the PID must be UNCHANGED

If the PID changes, the server is in the wrong cgroup and you are one unit
action away from losing an agent mid-task.
