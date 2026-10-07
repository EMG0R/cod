# COD

COD is agent-management software. It connects agents running on different
machines into a network, called an aquarium, so they can message each other
and so an arriving message lands in a running agent's live context.

This repository is the system. It is not anyone's aquarium. It contains the
machinery for building one: a message hub, a client, and worked examples. It
contains no node registry, no personas, no memory, and no tokens. You build
your own aquarium on your own server or laptop: your hub, your secret, your
nodes.

## Layout

- `aquarium/` - hub, client, systemd unit, docs and runnable examples.
  Start with `aquarium/QUICKSTART.md`.

## Requirements

Python 3.8 or newer (standard library only). `tmux` for message delivery into
agent sessions (optional).

## Privacy model

Each hub has its own secret, generated on first run on the machine that hosts
it. The hub listens on loopback by default. Nothing in this repository calls
out to any external service.

## License

MIT. See `LICENSE`.
