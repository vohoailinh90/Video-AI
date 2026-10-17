#!/usr/bin/env bash
# /usr/local/bin/codex-lead, installed root-owned by setup-vps-team.sh --with-codex.
#
# Starts Codex as the Codex team's lead (writing a spec, or auditing a pack) with
# the confinement docs/vps-team-codex.md describes. Run it as yourself, from
# /srv/team-codex/work/<id>. An audit reads a pack of text written by free models,
# so anything in it may be an instruction aimed at the lead:
#
#   - own CODEX_HOME (~/.codex-lead): none of your MCP servers or plugins, and its
#     config.toml is rewritten on every run, so nothing can be added to it;
#   - web search off;
#   - commands Codex runs get a minimal environment (shell_environment_policy.inherit
#     = core) and no login shell (allow_login_shell=false, or .profile would put your
#     exported keys back), so an injected `env` cannot copy them into verdict.md,
#     which `--from verdict` hands to the coder;
#   - workspace-write sandbox: writes only in this directory, no network for
#     commands, and no /tmp, $TMPDIR or other writable root (TMPDIR is inside
#     this directory);
#   - approval never: a command outside the sandbox fails instead of asking you;
#   - umask 007, so the spec and verdict it writes are readable by the pipeline user
#     (group team): with your own umask 077 they would be mode 600 and `team-codex
#     push` or `run --from verdict`, which run as team, would fail;
#   - the only option it accepts is --model: --search, --add-dir, --sandbox, -c and
#     friends would silently undo the lines above (run plain codex yourself if you
#     really mean to, knowing the audit is then unconfined).
#
# Not a boundary: the sandbox limits writes, not reads (docs/vps-team-codex.md).
set -euo pipefail

case "$(id -un)" in
  team|hermes) echo "codex-lead: run it as your own login, not as $(id -un)" >&2; exit 1 ;;
esac
# Codex's Linux sandbox is bubblewrap. Without it the sandbox cannot start (or the
# lead would run less confined than described), so stop instead of guessing.
if ! command -v bwrap >/dev/null 2>&1; then
  echo "codex-lead: bubblewrap (bwrap) is not installed, so Codex's sandbox cannot start: sudo apt-get install bubblewrap" >&2
  exit 1
fi
# Codex's working root is this directory, so it must be exactly one feature of the
# Codex team: not $HOME, not a subdirectory such as repo/ (worker-written), and not
# the Claude team's /srv/team/work/<id>, which has the same request.md and out/.
# pwd -P resolves symlinks, so a link into another team's directory fails too.
root=/srv/team-codex/work
here="$(pwd -P)"
id=""
case "${here}" in
  "${root}"/*) id="${here#"${root}"/}" ;;
esac
if ! [[ "${id}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || [[ "${id}" == *..* ]] || [[ "${id}" == *. ]] \
    || [ ! -f request.md ] || [ ! -d out ]; then
  echo "codex-lead: run it from ${root}/<id> itself (the Codex team's feature directory)" >&2
  exit 1
fi

extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --model|-m)
      if [ $# -lt 2 ] || [[ "$2" == -* ]]; then echo "codex-lead: $1 needs a model name" >&2; exit 1; fi
      extra+=("$1" "$2"); shift 2 ;;
    --model=?*) extra+=("$1"); shift ;;
    *) echo "codex-lead: only --model is accepted, not '$1' (it could undo the confinement)" >&2; exit 1 ;;
  esac
done

umask 007
export CODEX_HOME="$HOME/.codex-lead"
mkdir -p "${CODEX_HOME}"
printf 'web_search = "disabled"\n' > "${CODEX_HOME}/config.toml"
scratch="${PWD}/out/codex-tmp"
mkdir -p "${scratch}"
export TMPDIR="${scratch}" TMP="${scratch}" TEMP="${scratch}"
exec codex --sandbox workspace-write --ask-for-approval never \
  --config 'web_search="disabled"' \
  --config 'shell_environment_policy.inherit="core"' \
  --config allow_login_shell=false \
  --config sandbox_workspace_write.network_access=false \
  --config 'sandbox_workspace_write.writable_roots=[]' \
  --config sandbox_workspace_write.exclude_tmpdir_env_var=true \
  --config sandbox_workspace_write.exclude_slash_tmp=true ${extra[@]+"${extra[@]}"}
