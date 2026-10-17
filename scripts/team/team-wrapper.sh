#!/usr/bin/env bash
# /usr/local/bin/team, /usr/local/bin/team-codex and /usr/local/bin/team-video, installed by
# setup-vps-team.sh (the same file, under up to three names). Read-only commands run as you;
# everything that writes runs as user team, which owns /srv/team,
# /srv/team-codex and the worker containers.
#
# Which team this is comes from the name it is run under, never from a flag or
# the caller's environment: `team` is the Claude-led team, `team-codex` the
# Codex-led one, `team-video` the Claude-led team that makes HyperFrames videos
# with sound. The other teams share the first one's pipeline lock, so no two
# run a pipeline at once on a VPS that also runs CI.
#
# Hermes reaches this file through one sudoers rule (`sudo -u team`), and sudo
# sets SUDO_USER itself, so the restriction below cannot be talked around by a
# chat message: Hermes may look and start runs, never push, force or reconfigure.
set -euo pipefail
NAME="$(basename "$0")"
case "${NAME}" in
  team|team-wrapper.sh) export TEAM_HOME=/srv/team TEAM_LEAD=claude; unset TEAM_LOCK; NAME=team ;;
  team-codex) export TEAM_HOME=/srv/team-codex TEAM_LEAD=codex TEAM_LOCK=/srv/team/.run.lock ;;
  team-video) export TEAM_HOME=/srv/team-video TEAM_LEAD=video TEAM_LOCK=/srv/team/.run.lock ;;
  *) echo "team: installed under an unknown name '${NAME}'" >&2; exit 1 ;;
esac
TEAM_PY=/opt/team/team.py

if [ "${SUDO_USER:-}" = hermes ]; then
  case "${1:-}" in
    status|check-spec|run|doctor) ;;
    *) echo "team: hermes may only use status, check-spec, run and doctor" >&2; exit 1 ;;
  esac
  for arg in "$@"; do
    case "${arg}" in
      --force*) echo "team: --force is for the admin only" >&2; exit 1 ;;
    esac
  done
fi

case "${1:-}" in
  ""|-h|--help|check-spec|status|prompt) exec python3 "${TEAM_PY}" "$@" ;;
esac
if [ "$(id -un)" = team ]; then
  umask 007
  exec python3 "${TEAM_PY}" "$@"
fi
exec sudo -u team -- "/usr/local/bin/${NAME}" "$@"
