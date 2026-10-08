#!/usr/bin/env bash
# install-tank-node.sh — put the COD tank machinery on a node. Nothing else.
#
# ONE entrypoint, two callers: the Demiurge installer bundles it, and the COD
# app's Link Device wizard runs it over ssh. Two installers for one job would
# drift, and the drift would be silent.
#
# WHAT IT INSTALLS
#   ~/.local/bin/cod             the bus client
#   ~/.local/bin/claude-persist  the agent persistence layer
#   cod-tmux.service             owns the tmux server
#   cod-agents.service           resumes registered agents at boot
#   linger                       so the user manager survives logout
#
# WHAT IT DELIBERATELY DOES NOT DO
#   - No credentials. No bus token, no tailscale auth key, no ~/.cod-bus.conf.
#     This script lays down machinery and stops. Identity is a separate, later,
#     human-authorised step. A node that ships with a credential is a node whose
#     credential is in every image cut from it.
#   - It does not join a tank. A fresh install is DORMANT: Tailscale-ready,
#     bus-capable, member of nothing until someone runs Start or Join.
#   - It does not log anyone in to Claude.
#   - It touches no audio service, ever.
#
# Usage:
#   install-tank-node.sh [--dry-run] [--repo <url>] [--ref <branch>]
#
# Idempotent: safe to run repeatedly. Exits non-zero with a plain message if it
# cannot finish; it does not half-install quietly.
set -uo pipefail

REPO="${COD_REPO:-https://github.com/EMG0R/cod.git}"
REF="${COD_REF:-main}"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --repo) REPO="${2:?--repo needs a url}"; shift ;;
    --ref)  REF="${2:?--ref needs a ref}"; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac; shift
done

say()  { printf '[tank-install] %s\n' "$*"; }
die()  { printf '[tank-install] FAILED: %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then printf '[tank-install]   would: %s\n' "$*"; else "$@"; fi; }

[ "$(id -u)" != 0 ] || die "run as the node's own user, not root (this installs into \$HOME and a user systemd scope)"

# --- 1. prerequisites -------------------------------------------------------
missing=()
for b in git tmux python3 systemctl; do command -v "$b" >/dev/null 2>&1 || missing+=("$b"); done
if [ "${#missing[@]}" -gt 0 ]; then
  say "missing: ${missing[*]}"
  if command -v apt-get >/dev/null 2>&1; then
    run sudo apt-get update -qq
    run sudo apt-get install -y -qq "${missing[@]}" || die "could not install: ${missing[*]}"
  else
    die "missing ${missing[*]} and no apt-get to install them; install by hand and re-run"
  fi
else
  say "prerequisites present"
fi

# --- 2. fetch the public cod repo ------------------------------------------
SRC="$(mktemp -d)"; trap 'rm -rf "$SRC"' EXIT
say "fetching $REPO ($REF)"
if [ "$DRY" = 0 ]; then
  git clone --quiet --depth 1 --branch "$REF" "$REPO" "$SRC/cod" \
    || die "cannot clone $REPO — is this node online, and is the repo public?"
else
  say "  would: git clone --depth 1 --branch $REF $REPO"
fi
A="$SRC/cod/aquarium"

# Verify before installing, so a bad checkout fails here rather than halfway.
if [ "$DRY" = 0 ]; then
  for f in cod agents/claude-persist agents/systemd/cod-tmux.service agents/systemd/cod-agents.service; do
    [ -f "$A/$f" ] || die "checkout is missing aquarium/$f — wrong ref, or the repo layout moved"
  done
  python3 -m py_compile "$A/cod" || die "aquarium/cod does not compile; refusing to install it"
  bash -n "$A/agents/claude-persist" || die "claude-persist has a syntax error; refusing to install it"
  say "checkout verified"
fi

# --- 3. install ------------------------------------------------------------
BIN="$HOME/.local/bin"; UNITS="$HOME/.config/systemd/user"
run mkdir -p "$BIN" "$UNITS"
if [ "$DRY" = 0 ]; then
  install -m 0755 "$A/cod"                    "$BIN/cod"
  install -m 0755 "$A/agents/claude-persist"  "$BIN/claude-persist"
  install -m 0644 "$A/agents/systemd/cod-tmux.service"   "$UNITS/cod-tmux.service"
  install -m 0644 "$A/agents/systemd/cod-agents.service" "$UNITS/cod-agents.service"
else
  say "  would: install cod, claude-persist, cod-tmux.service, cod-agents.service"
fi
say "installed client + agent layer"

# --- 4. enable, without starting anything that needs identity --------------
# Enabling is safe: with no registered agents and no ~/.cod-bus.conf, these
# units come up and do nothing. That is the dormant state we want.
run systemctl --user daemon-reload
run systemctl --user enable cod-tmux.service cod-agents.service
if ! loginctl show-user "$USER" -p Linger --value 2>/dev/null | grep -q yes; then
  say "enabling linger (without it the user manager stops at logout and agents die)"
  run sudo loginctl enable-linger "$USER" || say "WARNING: could not enable linger; agents will not survive logout"
else
  say "linger already on"
fi

# --- 5. report --------------------------------------------------------------
say ""
say "done — this node is DORMANT and ready, holding no credentials."
say ""
say "  cod client      : $BIN/cod"
say "  agent layer     : $BIN/claude-persist"
say "  units enabled   : cod-tmux.service, cod-agents.service"
say "  tank membership : none (no ~/.cod-bus.conf, no token) — by design"
say ""
say "Next, as separate human-authorised steps:"
say "  1. join the tailnet   (operator-supplied key; never baked in)"
say "  2. get a bus token    (node-side, from the gate; never via a laptop)"
say "  3. write ~/.cod-bus.conf with COD_BUS_URL / COD_BUS_NODE / COD_BUS_TOKEN"
say "  4. register an agent  (claude-persist start <name>) once Claude is logged in"
