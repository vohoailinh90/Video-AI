#!/usr/bin/env python3
"""Conductor for the free-model coding team on a VPS.

You write the spec and audit the result in the lead's own CLI (Claude Code, or
Codex for the second team); free models write the tests, implement and
pre-review inside locked-down containers. Everything in between -- ordering,
retries, model fallback, commits, gates and the audit pack -- has a computable
answer, so this script does it rather than a model (CLAUDE.md, "Deterministic
work is not agent work"). The lead is only ever run by you: this script never
starts it.

    team new F12 --repo git@github.com:you/app.git   # clone + handoff templates
    team check-spec F12                              # after the lead wrote the spec
    team run F12 --detach                            # tester, coder, gates, review, pack
    team status                                      # where every feature stands
    team run F12 --from verdict                      # after a BLOCK verdict

Users, setup and the security model: docs/vps-team.md.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
PROMPTS = HERE / "prompts"
OPENCODE_CONFIG = HERE / "opencode.json"

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
HANDOFF = ("request.md", "spec.md", "tasks.md", "acceptance.md")
MOUNTED = HANDOFF + ("repo-map.txt",)
STAGES = ("tester", "coder", "review", "pack")
# The spec and audit prompts are one text for both leads, so the checks an auditor
# makes cannot drift apart; the lead-named entries are the names people type.
PROMPT_FILES = {"claude-spec": "spec", "claude-audit": "audit", "codex-spec": "spec", "codex-audit": "audit",
                "video-spec": "spec", "video-audit": "audit"}
PROMPT_NAMES = ("tester", "coder", "fix", "reviewer", "spec", "audit", *PROMPT_FILES)
SPEC_MAX_LINES = 120
REVIEW_MAX_LINES = 60
TODO_MARK = "TODO("
TASK_FIELDS = ("files:", "do not touch:", "verify:")
REVIEW_START, REVIEW_END = "=== REVIEW ===", "=== END ==="
LOCKFILES = ("*.lock", "package-lock.json", "pnpm-lock.yaml", "npm-shrinkwrap.json")
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.[^/]+$|\.(test|spec)\.[^/]+$|(^|/)conftest\.py$"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Host-side git must never run code a worker could have planted. Workers never
# see the real .git (it sits behind a tmpfs in their container); these settings
# close the remaining doors -- hooks, fsmonitor, ext:: transports -- in case a
# planted file ever reaches it some other way.
GIT_SAFE = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never")

# OpenCode provider id -> the environment variable its SDK reads. Override or
# add one with TEAM_KEY_<PROVIDER>=<VAR> in team.env.
PROVIDER_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_GENERATIVE_AI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "opencode": "OPENCODE_API_KEY",
}
# OpenAI-compatible model listings, used by `doctor --ping` and `models`.
MODELS_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "nvidia": "https://integrate.api.nvidia.com/v1/models",
}
# OpenCode resolves a model only from its catalog: a provider can list a model
# (`team models`) before models.dev does, and the worker then cannot start it.
OPENCODE_CATALOG_URL = "https://models.dev/api.json"
# The video team's smoke test: a baked 3 s project rendered, then judged by the same script the gates
# use, and one sentence of narration. Both run in the hardened worker container with no network.
VIDEO_IMAGE_DEFAULT = "team-worker:latest"
SMOKE_RENDER = ("cp -r /usr/local/share/team-video/smoke /tmp/smoke && cd /tmp/smoke && "
                "hyperframes render --quality draft --output draft.mp4 && "
                "python3 /usr/local/lib/team-video/video_gates.py draft.mp4 --expect expected.json")
SMOKE_NARRATION = 'hyperframes tts "Hello from the video team." --output /tmp/voice.wav && test -s /tmp/voice.wav'
# Providers that resell other vendors' models: the family is the vendor segment.
AGGREGATORS = ("openrouter", "opencode", "nvidia")
# One publisher, several slugs (NVIDIA's, OpenRouter's, a direct provider's id).
FAMILY_ALIASES = {"deepseek-ai": "deepseek", "meta-llama": "meta", "mistralai": "mistral", "minimaxai": "minimax"}

DEFAULTS = {
    "TEAM_IMAGE": "team-worker:latest",
    "TEAM_BASE": "main",
    "TEAM_MODELS_TESTER": "",
    "TEAM_MODELS_CODER": "",
    "TEAM_MODELS_REVIEWER": "",
    "TEAM_CODER_ATTEMPTS": "3",
    "TEAM_WORKER_TIMEOUT": "1800",
    "TEAM_WORKER_MEMORY": "3g",
    "TEAM_WORKER_CPUS": "2",
    "TEAM_WORKER_NETWORK": "team-net",
    "TEAM_WORKER_TMP": "1g",
    "TEAM_WORKER_SHM": "",
    "TEAM_GATES_NETWORK": "none",
    "TEAM_GATES_SETUP": "",
    "TEAM_GATE_TIMEOUT": "900",
    "TEAM_PACK_MAX_LINES": "1500",
    "TEAM_PACK_MAX_BYTES": "250000",
    "TEAM_LOG_MAX_BYTES": "20000000",
    "TEAM_WORKSPACE_GROWTH_BYTES": "3000000000",
    "TEAM_MIN_FREE_BYTES": "1000000000",
    "TEAM_WORKSPACE_GROWTH_FILES": "500000",
    "TEAM_MAP_MAX_LINES": "600",
    "TEAM_GIT_NAME": "team-bot",
    "TEAM_GIT_EMAIL": "team-bot@localhost",
}

# Paths whose change can act outside the feature: CI on the self-hosted runner
# (same VPS), or instructions read by the next agent, Claude included.
# Build and cache output a worker's own test run leaves in the tree. Kept out of
# every conductor commit through .git/info/exclude, which workers cannot reach;
# a file the repository already tracks stays tracked.
LOCAL_EXCLUDES = ("__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", ".tox/",
                  ".venv/", "node_modules/", ".coverage", "*.egg-info/")
# The video team's own output, as Video-AI's .gitignore has it: each project's draft renders, snapshots and the
# HyperFrames check cache. Only for that team: a code repository may well have a `src/renders/` package, and an
# exclude pattern deletes what it matches (purge_untracked).
VIDEO_EXCLUDES = ("renders/", "snapshots/", ".hyperframes/")
# Worker-chosen paths per git command line: how many there are is the worker's
# choice, the size of argv is not (ARG_MAX). 200 paths of PATH_MAX fit easily.
ARG_BATCH = 200
# `pack --force` lifts TEAM_PACK_MAX_BYTES, but the diff it quotes still stops here, so it is never held whole.
PACK_FORCE_DIFF_BYTES = 20_000_000
# A list of changed paths is read only this far (a worker can make empty files with long names almost for free), and a list of
# every path in the tree this far; past it the conductor stops with "too many paths" instead of holding gigabytes of names.
PATHS_MAX_BYTES = 8_000_000
TREE_PATHS_MAX_BYTES = 64_000_000
# One handoff file is copied for a worker only up to this size (gates.log is capped at TEAM_LOG_MAX_BYTES, 20 MB by default).
HANDOFF_FILE_MAX_BYTES = 64_000_000
READ_MAX_BYTES = 64_000_000  # the most `read` takes from one file of the feature directory
CUT_NOTE = "\n[team] diff cut at {limit} bytes: the rest of it was not read\n"
SENSITIVE_PATH_RE = re.compile(
    r"(^|/)(\.github|\.claude|\.gitlab-ci\.yml|\.gitattributes|\.codex|\.agents|CLAUDE\.md|AGENTS(?:\.override)?\.md|\.cursorrules|\.hermes\.md"
    r"|opencode\.json)(/|$)"
)
VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(APPROVE|BLOCK)\s*$", re.MULTILINE)
OUTPUT_TAIL_BYTES = 200_000

SIG_JS = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type|enum)\b")
SIG_JVM = re.compile(r"^\s*(?:public|internal|protected)\s+.*(?:class|interface|enum|record|\()")
SIGNATURES = {
    ".py": re.compile(r"^\s*(?:async\s+def|def|class)\s+\w+"),
    ".js": SIG_JS, ".jsx": SIG_JS, ".mjs": SIG_JS, ".ts": SIG_JS, ".tsx": SIG_JS,
    ".go": re.compile(r"^func\s+"),
    ".rs": re.compile(r"^\s*pub\s+(?:async\s+)?(?:fn|struct|enum|trait)\s+"),
    ".java": SIG_JVM, ".kt": SIG_JVM, ".cs": SIG_JVM,
}


# --------------------------------------------------------------------- basics

def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def say(message: str) -> None:
    print(f"[team {time.strftime('%H:%M:%S')}] {message}", flush=True)


def read(path: Path) -> str:
    """The text of a plain file, "" when there is none.

    The feature directory is group-writable, so whatever the lead left at `path` is not trusted: a link (to workers.env, say)
    is refused instead of followed, a named pipe cannot block the read, and a file past READ_MAX_BYTES is not slurped."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except (FileNotFoundError, NotADirectoryError):
        return ""
    except OSError as exc:
        raise SystemExit(f"{path} is a link or cannot be read ({exc.strerror}): refusing to use it") from None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise SystemExit(f"{path} is not a plain file: refusing to use it")
        data = bytearray()
        while len(data) <= READ_MAX_BYTES:  # in chunks: one read(READ_MAX_BYTES + 1) allocates all of it, even for a short file
            chunk = handle.read(min(1 << 20, READ_MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data += chunk
    if len(data) > READ_MAX_BYTES:
        raise SystemExit(f"{path} is larger than {READ_MAX_BYTES} bytes: refusing to use it")
    return bytes(data).decode("utf-8")


def write_file(path: Path, text: str) -> None:
    """Put `text` at `path` by writing a new file beside it and renaming it over. A link the lead left at `path` is replaced,
    never written through (gates.log -> workers.env would have had the gate log written over the keys)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o664)  # the lead's login reads what the conductor writes here
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def tail(path: Path, lines: int) -> str:
    return tail_text(read(path), lines)


def last_line(text: str) -> str:
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    return rows[-1][:200] if rows else "no output"


def tail_text(text: str, lines: int) -> str:
    rows = text.rstrip("\n").splitlines()
    cut = rows[-lines:]
    return ("" if len(rows) <= lines else f"... ({len(rows) - lines} earlier lines cut)\n") + "\n".join(cut)


def render(path: Path, **values: object) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def team_home() -> Path:
    return Path(os.environ.get("TEAM_HOME", "/srv/team"))


class Lead(NamedTuple):
    """Who designs the work and audits the result. Always run by the operator in
    their own login, never by this script."""
    name: str      # TEAM_LEAD value
    command: str   # the wrapper in /usr/local/bin; also the branch prefix
    container: str  # container name prefix; no lead's may start with another's `<prefix>-`
    title: str     # for messages
    cli: str       # what the operator types to start the lead (Codex: the confined launcher, never plain codex)


# Container names are `<container>-<id>-<role>` and ids may contain `-`, so a prefix
# that extends another (`team-codex` after `team`) lets Claude's feature `codex-F1`
# and Codex's feature `F1` name the same container. `codex-team` never begins with `team-`.
LEADS = {"claude": Lead("claude", "team", "team", "Claude Code", "claude"),
         "codex": Lead("codex", "team-codex", "codex-team", "Codex", "codex-lead"),
         # The video team: Claude Code is still the architect, but the work is a HyperFrames
         # video with sound, so it has its own prompts, templates and worker image.
         "video": Lead("video", "team-video", "video-team", "Claude Code", "claude")}


def team_lead() -> Lead:
    """Fixed by the root-owned wrapper through TEAM_LEAD, never by team.env, which
    the team group can edit: which login audits is not a setting."""
    name = os.environ.get("TEAM_LEAD", "claude")
    if name not in LEADS:
        raise SystemExit(f"TEAM_LEAD={name!r}: expected one of {', '.join(LEADS)}")
    return LEADS[name]


def shipped(directory: Path, name: str) -> Path:
    """A prompt or template of the selected team: `<directory>/<lead>/<name>` when the lead
    ships its own (the video team), else the shared `<directory>/<name>`."""
    own = directory / team_lead().name / name
    return own if own.is_file() else directory / name


SYSTEMD_RUNTIME = Path("/run/systemd/system")


EGRESS_OK = Path("/run/team-egress.ok")
EGRESS_OK_MAX_AGE_S = 90  # the check timer runs every 20 s (setup-vps-team.sh): a miss or two must not read as down
EGRESS_CHECK = ["/usr/local/sbin/team-egress", "--check"]


def live_egress() -> tuple[str | None, str | None]:
    """Run the root-owned check now: (the network it verified, None), or (None, why it could not)."""
    argv = EGRESS_CHECK if os.geteuid() == 0 else ["sudo", "-n", *EGRESS_CHECK]  # one sudoers rule allows exactly this
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, f"{' '.join(argv)} timed out"
    except OSError as exc:
        return None, f"{' '.join(argv)}: {exc}"
    if result.returncode:
        return None, last_line(result.stderr) if result.stderr.strip() else f"{' '.join(argv)} exited {result.returncode}"
    return result.stdout.strip(), None


def egress_problem(network: str | None = None, live: bool = False) -> str | None:
    """Workers may reach the internet and nothing else because iptables rules, installed by the team-egress unit
    (setup-vps-team.sh), match the worker network's subnet. The unit is a oneshot that stays "active" after the rules are
    flushed, so its state proves nothing: the root-owned check (`team-egress --check`) asks iptables about every rule and
    the network's subnet. `live` runs it now (a launch must: a cached answer can be up to a minute old); otherwise the
    answer is the proof file a timer keeps fresh, which is enough for a diagnostic. `network` is the one about to be used."""
    if not SYSTEMD_RUNTIME.is_dir() or not shutil.which("systemctl"):
        return None  # no systemd to ask: a container, CI or a test
    fix = "rerun setup-vps-team.sh; it needs iptables and sudo"
    if subprocess.run(["systemctl", "is-active", "--quiet", "team-egress.service"]).returncode:
        return f"team-egress.service is not active: worker containers are not limited to the internet ({fix})"
    if live:
        verified, why = live_egress()
        if why:
            return f"the egress rules could not be verified just now ({why}): workers may not be limited to the internet ({fix})"
    else:
        try:
            verified = EGRESS_OK.read_text(encoding="utf-8").strip()
            age = time.time() - EGRESS_OK.stat().st_mtime
        except OSError:
            return (f"the egress rules were never verified ({EGRESS_OK} is missing, or `team-egress --check` fails; "
                    f"see journalctl -u team-egress-check): workers may not be limited to the internet ({fix})")
        if age > EGRESS_OK_MAX_AGE_S:
            return (f"the egress rules were last verified {age:.0f}s ago (more than {EGRESS_OK_MAX_AGE_S}s): "
                    f"journalctl -u team-egress-check ({fix})")
    if network and network != verified:
        return (f"network {network} is not covered by the egress rules (they were verified for {verified}): "
                f"workers on it are not limited to the internet; use {verified}")
    return None


def lock_path(home: Path) -> Path:
    """One lock for the whole VPS: the second team's wrapper points TEAM_LOCK at the
    first team's, so two pipelines never run at once on a machine CI shares."""
    return Path(os.environ.get("TEAM_LOCK") or home / ".run.lock")


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines, '#' comments, optional quotes. Read as data, never executed."""
    values: dict[str, str] = {}
    for number, raw in enumerate(read(path).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"{path}:{number}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def load_config(home: Path) -> dict[str, str]:
    cfg = dict(DEFAULTS)
    cfg.update(parse_env_file(home / "team.env"))
    return cfg


def load_keys(home: Path) -> dict[str, str]:
    return parse_env_file(home / "workers.env")


def models_for(cfg: dict[str, str], role: str) -> list[str]:
    return cfg.get(f"TEAM_MODELS_{role.upper()}", "").split()


def provider_of(model: str) -> str:
    return model.split("/", 1)[0]


def family_of(model: str) -> str:
    parts = model.split("/")
    vendor = parts[1] if parts[0] in AGGREGATORS and len(parts) > 2 else parts[0]
    return FAMILY_ALIASES.get(vendor, vendor)


def key_env(cfg: dict[str, str], provider: str) -> str | None:
    return cfg.get("TEAM_KEY_" + re.sub(r"\W", "_", provider.upper())) or PROVIDER_KEYS.get(provider)


class Feature:
    """One requirement: handoff files, its own clone, and the pipeline's outputs."""

    def __init__(self, home: Path, fid: str):
        if not ID_RE.fullmatch(fid) or ".." in fid or fid.endswith((".", ".lock")):
            raise SystemExit(f"invalid feature id {fid!r}: letters, digits, '.', '_' and '-' only "
                             "(no '..', not ending in '.' or '.lock')")
        self.id = fid
        self.home = home
        self.dir = home / "work" / fid
        self.repo = self.dir / "repo"
        self.out = self.dir / "out"
        self.branch = f"{team_lead().command}/{fid}"

    def file(self, name: str) -> Path:
        return self.dir / name

    def require(self) -> None:
        if not self.repo.is_dir():
            raise SystemExit(f"no feature {self.id}: run `{team_lead().command} new {self.id} --repo ...` first")
        # Docker resolves a link in a bind source as root: `repo` pointing at the team home would hand every key to a worker.
        for path in (self.dir, self.repo, self.out):
            if path.is_symlink():
                raise SystemExit(f"{path} is a link: refusing to use feature {self.id}")

    def load_state(self) -> dict:
        text = read(self.out / "state.json")
        return json.loads(text) if text else {}

    def save_state(self, state: dict) -> None:
        state["updated"] = now()
        write_file(self.out / "state.json", json.dumps(state, indent=2) + "\n")


def verdict_of(text: str) -> str | None:
    """The first `VERDICT:` line decides; APPROVE or BLOCK, nothing else counts."""
    match = VERDICT_RE.search(text)
    return match.group(1) if match else None


def warn(state: dict, message: str, round: str | None = None) -> None:
    state.setdefault("warnings", []).append(message)
    if round:  # remembered apart, so the next round of that stage can drop exactly these (drop_round_warnings)
        state.setdefault(f"{round}_warnings", []).append(message)
    say(f"warning: {message}")


# ------------------------------------------------------------------------ git

# What `team new` leaves in a feature clone's .git/config (clone, `checkout -b`, and the two `git config` calls). Anything else is
# refused: the file is writable by the audit session, and a setting such as core.worktree, core.fsmonitor, core.sshCommand, a
# filter driver, an include or an alias would have every host-side git command act on, or run, what the setting names.
SAFE_REPO_KEYS = frozenset({"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase",
                            "core.precomposeunicode", "core.symlinks", "remote.origin.url", "remote.origin.fetch",
                            "user.name", "user.email"})
SAFE_REPO_KEY_RE = re.compile(r"branch\..+\.(remote|merge)")
_checked_repos: dict[str, tuple] = {}


def check_repo(repo: Path) -> None:
    """Refuse a feature clone whose git directory or configuration is not what `team new` made (see SAFE_REPO_KEYS)."""
    git_dir = repo / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir() or (git_dir / "commondir").exists():
        raise SystemExit(f"{git_dir} is not the plain git directory `{team_lead().command} new` made: refusing to run git in {repo}")
    config = git_dir / "config"
    try:
        info = config.lstat()
    except OSError:
        raise SystemExit(f"{config} is missing: refusing to run git in {repo}") from None
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"{config} is not a plain file: refusing to run git in {repo}")
    stamp = (info.st_mtime_ns, info.st_size, info.st_ino, git_dir.stat().st_ino)
    if _checked_repos.get(str(repo)) == stamp:
        return
    # `--file` reads that one file: no repository discovery, no worktree, nothing it names is run or followed
    listed = subprocess.run(["git", "config", "--file", str(config), "--list", "-z"], capture_output=True, env=base_env())
    if listed.returncode:
        raise SystemExit(f"{config} cannot be read by git: refusing to run git in {repo}")
    for entry in listed.stdout.decode("utf-8", "replace").split("\0"):
        key, _, value = entry.partition("\n")
        key = key.lower()
        if not key:
            continue
        ok = key in SAFE_REPO_KEYS or SAFE_REPO_KEY_RE.fullmatch(key)
        ok = ok and not (key == "core.bare" and value != "false") and not (key == "core.repositoryformatversion" and value != "0")
        if not ok:
            raise SystemExit(f"{config} sets {key}, which `{team_lead().command} new` never does and which could send git elsewhere: "
                             f"refusing to run git in {repo}. Remove it: git -C {repo} config --unset {key}")
    _checked_repos[str(repo)] = stamp


def git_argv(repo: Path, *args: str) -> list[str]:
    """The command line for a host-side git command in a feature clone, once its configuration is known to be ordinary."""
    check_repo(repo)
    return ["git", *GIT_SAFE, "-C", str(repo), *args]


def git(repo: Path, *args: str, check: bool = True) -> str:
    # errors="replace": a diff can carry bytes that are not UTF-8 (a Latin-1
    # source file); a model-written file must never crash the conductor.
    result = subprocess.run(git_argv(repo, *args), capture_output=True, text=True, errors="replace")
    if check and result.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def read_capped(repo: Path, args: tuple[str, ...] | list[str], limit: int) -> tuple[bytes, bool]:
    """`git *args` output, at most `limit` bytes of it; True when there was more. Git is stopped at the limit rather than
    waited for, so output of gigabytes is never held in memory or written out whole."""
    with subprocess.Popen(git_argv(repo, *args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        data = bytearray()
        while len(data) <= limit:  # in chunks: one read(limit + 1) allocates its whole size at once, even for a short output
            chunk = proc.stdout.read1(min(1 << 16, limit + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        cut = len(data) > limit
        if cut:
            proc.kill()
        elif proc.wait():
            raise SystemExit(f"git {' '.join(args)} failed")
    return bytes(data[:limit]), cut


def too_many_paths(args: tuple[str, ...] | list[str], limit: int) -> SystemExit:
    return SystemExit(f"too many paths: `git {' '.join(args)}` lists more than {limit} bytes of names. "
                      "Nothing that size can be audited: split the feature")


def git_paths(repo: Path, *args: str, limit: int | None = None) -> list[str]:
    """A -z path list that round-trips: surrogateescape keeps a non-UTF-8 name
    byte-exact when it goes back to git as an argument. Text meant for reading
    goes through git() and its lossy decode instead. Stops with "too many paths"
    past `limit` (PATHS_MAX_BYTES) instead of holding the whole list."""
    limit = PATHS_MAX_BYTES if limit is None else limit
    data, cut = read_capped(repo, args, limit)
    if cut:
        raise too_many_paths(args, limit)
    return [os.fsdecode(path) for path in data.split(b"\0") if path]


def git_listing(repo: Path, *args: str) -> str:
    """git_paths for output meant to be read as text (a -z listing shown in the pack): the same ceiling, lossy decode."""
    data, cut = read_capped(repo, args, PATHS_MAX_BYTES)
    if cut:
        raise too_many_paths(args, PATHS_MAX_BYTES)
    return data.decode("utf-8", "replace")


def git_capped(repo: Path, *args: str, limit: int) -> tuple[str, bool]:
    """`git *args` output as text, at most `limit` bytes of it; True when there was more."""
    data, cut = read_capped(repo, args, limit)
    return data.decode("utf-8", "replace"), cut


def readable_diff(repo: Path) -> tuple[str, ...]:
    """`git diff` as every reviewer and the auditor reads it.

    Attributes come from an empty tree, never from the repository: a worker can
    commit a .gitattributes marking any text file `-diff` or `binary` so that
    only "Binary files differ" is printed. With the repository's attributes out
    of the way, binary-ness is decided by content alone, so a real binary is
    still summarised instead of dumped, and no diff driver or textconv runs.
    """
    empty_tree = git(repo, "hash-object", "-t", "tree", "/dev/null").strip()
    return (f"--attr-source={empty_tree}", "diff", "--no-ext-diff", "--no-textconv")


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def has_changes(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain").strip())


def restore_permissions(repo: Path) -> None:
    """A worker runs as this same user and can chmod 000 what it wrote, so git
    could neither add, reset nor clean it. Give the owner back read and write
    (and search on directories); symlinks are skipped, never followed."""
    def owner_access(path: str) -> None:
        mode = os.lstat(path).st_mode
        if not stat.S_ISLNK(mode):
            extra = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if stat.S_ISDIR(mode) else 0)
            os.chmod(path, stat.S_IMODE(mode) | extra)
    owner_access(str(repo))
    for root, dirs, files in os.walk(repo):  # top-down: a directory is fixed before it is listed
        if root == str(repo):
            dirs[:] = [name for name in dirs if name != ".git"]
        for name in dirs + files:
            owner_access(os.path.join(root, name))


def local_excludes() -> tuple[str, ...]:
    return LOCAL_EXCLUDES + (VIDEO_EXCLUDES if team_lead().name == "video" else ())


def purge_untracked(repo: Path) -> None:
    """Delete every untracked file, ignored ones too (-x): LOCAL_EXCLUDES makes a
    worker's .venv or node_modules ignored, and the next container, holding
    another provider's key, must not find what it planted. -ff: nested repos."""
    git(repo, "clean", "-ffdqx")


def discard(repo: Path) -> None:
    restore_permissions(repo)
    git(repo, "reset", "-q", "--hard")
    purge_untracked(repo)


def ensure_excludes(repo: Path) -> None:
    exclude = repo / ".git" / "info" / "exclude"
    current = read(exclude)
    missing = [pattern for pattern in local_excludes() if pattern not in current.splitlines()]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        separator = "" if not current or current.endswith("\n") else "\n"
        write_file(exclude, current + separator + "\n".join(missing) + "\n")


def untrack_caches(repo: Path, base: str) -> None:
    """Drop from the index every cache the pipeline added; one tracked at base is
    the repository's own choice. Run after `git add -A`: a worker's .gitignore
    outranks info/exclude, so `!__pycache__/` there stages a cache anyway. It
    also clears a cache committed before LOCAL_EXCLUDES existed, which no worker
    can untrack (it sees no .git) and every test run rewrote."""
    if subprocess.run(git_argv(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{tree}}"), capture_output=True).returncode:
        return  # no base to tell the pipeline's caches from the repository's
    at_base = set(git_paths(repo, "ls-tree", "-r", "-z", "--name-only", base, limit=TREE_PATHS_MAX_BYTES))
    excludes = [f"--exclude={pattern}" for pattern in local_excludes()]
    tracked = git_paths(repo, "ls-files", "-z", "--cached", "--ignored", *excludes, limit=TREE_PATHS_MAX_BYTES)
    added = [path for path in tracked if path not in at_base]
    if added:  # on stdin, as plain paths (not pathspecs), however many there are
        result = subprocess.run(git_argv(repo, "update-index", "-z", "--force-remove", "--stdin"),
                                input=b"\0".join(os.fsencode(path) for path in added), capture_output=True)
        if result.returncode:
            raise SystemExit(f"git update-index failed: {result.stderr.decode('utf-8', 'replace').strip()}")


def changed_bytes(repo: Path) -> int:
    """Bytes of the regular files `git add -A` would store: those `git status` lists as modified or untracked."""
    args = ("status", "--porcelain=v1", "-z", "--untracked-files=all")
    data, cut = read_capped(repo, args, PATHS_MAX_BYTES)
    if cut:
        raise too_many_paths(args, PATHS_MAX_BYTES)
    total, skip = 0, False
    for record in data.split(b"\0"):
        if skip:  # a rename or copy is followed by the name it came from
            skip = False
            continue
        if len(record) < 4:
            continue
        skip = record[:1] in (b"R", b"C")
        try:
            info = os.lstat(repo / os.fsdecode(record[3:]))
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
    return total


def commit_all(repo: Path, message: str, base: str, min_free: int = 0) -> bool:
    """Commit the whole working tree, then delete what stayed out of the commit,
    so the next worker starts from exactly HEAD. The conductor commits, never
    the model.

    `git add -A` writes a loose object for every changed file: an output just inside the workspace allowance costs about that
    much again. So the changed files must fit in the free space with `min_free` to spare, or the attempt is discarded and
    the run stops, rather than the disk filling in the middle of staging."""
    restore_permissions(repo)
    ensure_excludes(repo)
    try:
        need = changed_bytes(repo)
    except SystemExit:  # too many changed paths: nothing of this attempt is kept
        discard(repo)
        raise
    free = shutil.disk_usage(repo).free
    if free < need + min_free:
        discard(repo)
        raise SystemExit(f"not enough free disk space to stage this change: {need} bytes of changed files, {free} bytes free, "
                         f"{min_free} to keep in reserve (TEAM_MIN_FREE_BYTES). The attempt was discarded; free some space and run again")
    git(repo, "add", "-A")
    untrack_caches(repo, base)
    staged = subprocess.run(git_argv(repo, "diff", "--cached", "--quiet")).returncode != 0
    if staged:
        git(repo, "commit", "-q", "--no-verify", "-m", message)
    purge_untracked(repo)
    return staged


def merge_base(f: Feature, state: dict) -> str:
    base = state.get("base", "main")
    result = subprocess.run(git_argv(f.repo, "merge-base", "HEAD", f"origin/{base}"), capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else base


def export_head(repo: Path, dest: Path) -> None:
    """A clean checkout of HEAD: untracked or ignored files a worker left behind
    do not exist here, and neither does .git."""
    check_repo(repo)
    subprocess.run(
        ["git", *GIT_SAFE, "clone", "-q", "--no-hardlinks", "--", str(repo), str(dest)],
        check=True, capture_output=True,
    )
    shutil.rmtree(dest / ".git")


# ------------------------------------------------------------- spec handling

def map_files(files: list[str]) -> list[str]:
    """What the repo map lists. A video repository carries upstream HyperFrames skills (hundreds of
    files, pinned by skills-lock.json) that would fill the whole map: the video team lists each
    skill's SKILL.md and nothing below it, so `videos/` and the repo's own files stay visible."""
    if team_lead().name != "video":
        return files
    return [path for path in files
            if not path.startswith(".claude/skills/") or (path.endswith("/SKILL.md") and path.count("/") == 3)]


def repo_map(repo: Path, max_lines: int) -> str:
    tracked = git(repo, "ls-files").splitlines()
    files = map_files(tracked)
    omitted = f", {len(tracked) - len(files)} upstream skill files not listed" if len(files) != len(tracked) else ""
    lines = [f"# repo map ({len(tracked)} tracked files{omitted})", "", "## signatures"]
    for rel in files:
        pattern = SIGNATURES.get(Path(rel).suffix)
        path = repo / rel
        if pattern is None or path.is_symlink() or not path.is_file() or path.stat().st_size > 512_000:
            continue
        source = path.read_text(encoding="utf-8", errors="replace").splitlines()
        found = [row.strip()[:160] for row in source if pattern.match(row)][:30]
        if found:
            lines += [f"{rel}:", *("  " + row for row in found)]
    lines += ["", "## files", *files]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... truncated at {max_lines} lines"]
    return "\n".join(lines) + "\n"


def parse_acceptance(text: str) -> tuple[list[str], str | None]:
    """(the gate commands, what is wrong with how they are written). Each line of a ```bash/```sh block is one command and
    a trailing '\\' continues it; a continuation left open at the closing fence or at the end of the file is an error,
    and what it had collected is dropped rather than glued to the next block's first command."""
    commands: list[str] = []
    fence: str | None = None
    pending = ""
    error: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            if pending:
                error = f"a command ends with a backslash at the end of its block: {pending.strip()[:80]!r}"
                pending = ""
            fence = line[3:].strip().lower() if fence is None else None
            continue
        if fence not in ("bash", "sh", "shell") or not line or line.startswith("#"):
            continue
        if line.startswith("$ "):
            line = line[2:]
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        commands.append(pending + line)
        pending = ""
    if pending:
        error = f"a command ends with a backslash at the end of the file: {pending.strip()[:80]!r}"
    return commands, error


def acceptance_commands(text: str) -> list[str]:
    return parse_acceptance(text)[0]


def acceptance_error(text: str) -> str | None:
    return parse_acceptance(text)[1]


def check_spec(f: Feature) -> list[str]:
    problems = []
    for name in HANDOFF:
        path = f.file(name)
        if not path.is_file():
            problems.append(f"{name}: missing")
        elif TODO_MARK in read(path):
            problems.append(f"{name}: still contains a {TODO_MARK}...) placeholder")
    spec_lines = len(read(f.file("spec.md")).splitlines())
    if spec_lines > SPEC_MAX_LINES:
        problems.append(f"spec.md: {spec_lines} lines, the limit is {SPEC_MAX_LINES}")
    sections = re.split(r"(?m)^##\s+", read(f.file("tasks.md")))[1:]
    if f.file("tasks.md").is_file() and not sections:
        problems.append("tasks.md: no '## ' task sections")
    for section in sections:
        title = section.splitlines()[0].strip() if section.strip() else "?"
        for field in TASK_FIELDS:
            if not re.search(rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*\S", section):
                problems.append(f"tasks.md: task '{title}' has no '{field[:-1].capitalize()}:' line with a value")
    if f.file("acceptance.md").is_file() and not acceptance_commands(read(f.file("acceptance.md"))):
        problems.append("acceptance.md: no command inside a ```bash block")
    broken = acceptance_error(read(f.file("acceptance.md")))
    if broken:
        problems.append(f"acceptance.md: {broken}")
    return problems


# --------------------------------------------------------------- containers

def container_name(f: Feature, role: str) -> str:
    return f"{team_lead().container}-{f.id}-{role}"


def hardening(cfg: dict[str, str]) -> list[str]:
    return [
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
        "--memory", cfg["TEAM_WORKER_MEMORY"], "--cpus", cfg["TEAM_WORKER_CPUS"],
        "--read-only", "--tmpfs", f"/tmp:rw,exec,nosuid,size={cfg['TEAM_WORKER_TMP']}",
        "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp/home",
        # Docker copies a container's output into its own json-file log, which is not rotated by default, whether or not
        # `docker run` is attached. run_docker reads the pipe and keeps its own capped log, so Docker keeps none.
        "--log-driver", "none",
        # Chrome (the video team's renders) crashes on Docker's default 64 MB /dev/shm.
        *(["--shm-size", cfg["TEAM_WORKER_SHM"]] if cfg["TEAM_WORKER_SHM"] else []),
    ]


def operator_inputs(f: Feature) -> Path | None:
    """The files the operator supplied (the video team's videos/<id>.inputs/), when the checkout has them. They are
    originals the audit pack cannot show as altered, so builders get them read-only. Never through a symlink: docker
    resolves a bind source on the host."""
    if team_lead().name != "video":
        return None
    path = f.repo / "videos" / f"{f.id}.inputs"
    if path.is_symlink() or not path.is_dir() or not os.path.realpath(path).startswith(os.path.realpath(f.repo) + os.sep):
        return None
    return path


def worker_argv(cfg: dict[str, str], f: Feature, role: str, model: str,
                mounts: dict[str, Path], prompt: str) -> list[str]:
    argv = [
        "docker", "run", "--rm", "--name", container_name(f, role),
        "--network", cfg["TEAM_WORKER_NETWORK"], *hardening(cfg),
        "-e", "OPENCODE_CONFIG=/etc/team/opencode.json",
        "-v", f"{OPENCODE_CONFIG}:/etc/team/opencode.json:ro",
        "-v", f"{f.repo}:/work" + (":ro" if role == "reviewer" else ""),
        "--mount", "type=tmpfs,destination=/work/.git,tmpfs-size=1m",
        "-w", "/work",
    ]
    inputs = operator_inputs(f)
    if inputs and role != "reviewer":  # the reviewer's checkout is read-only as a whole
        argv += ["-v", f"{inputs}:/work/videos/{f.id}.inputs:ro"]
    for name, path in sorted(mounts.items()):
        argv += ["-v", f"{path}:/handoff/{name}:ro"]
    env_name = key_env(cfg, provider_of(model))
    if env_name:
        argv += ["-e", env_name]  # value travels in worker_env(), never on a command line
    return argv + [cfg["TEAM_IMAGE"], "opencode", "run", "--model", model, prompt]


def base_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "LANG", "DOCKER_HOST", "DOCKER_CONFIG")
    return {k: v for k, v in os.environ.items() if k in keep}


def worker_env(cfg: dict[str, str], keys: dict[str, str], model: str) -> dict[str, str]:
    """The docker client's environment: only the one key this model's provider needs.
    Code a model writes runs next to that key, so no other key is ever in reach."""
    env = base_env()
    name = key_env(cfg, provider_of(model))
    if name and keys.get(name):
        env[name] = keys[name]
    return env


def network_of(argv: list[str]) -> str | None:
    """The `--network` a `docker run` argv names (None: the flag is missing, so docker's default bridge)."""
    return argv[argv.index("--network") + 1] if "--network" in argv else None


WORKSPACE_POLL_S = 2.0


def workspace_usage(path: Path, max_entries: int | None = None) -> tuple[int, int, bool]:
    """(bytes the files under `path` really occupy, number of entries under it, whether the scan stopped for passing
    `max_entries`). A sparse file counts what it uses and symlinks are not followed. Every file, link and directory is an
    entry: empty ones occupy no blocks, yet each costs an inode, so bytes alone never see them. The scan stops at the first
    entry past `max_entries`, which keeps its time bounded however many a container makes."""
    try:
        total = os.lstat(path).st_blocks * 512
    except OSError:
        total = 0
    count, pending = 0, [str(path)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    count += 1
                    if max_entries is not None and count > max_entries:
                        return total, count, True
                    try:
                        total += entry.stat(follow_symlinks=False).st_blocks * 512
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count, False


def disk_usage(path: Path) -> int:
    """Bytes the files under `path` really occupy."""
    return workspace_usage(path)[0]


@contextlib.contextmanager
def open_for_append(path: Path, what: str):
    """`path` opened for appending, never through a link: the feature directory is group-writable, and a link left at a log's
    name would have `what` written into whatever it points to (workers.env, a seal), as the privileged team user."""
    try:
        handle = os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o664), "ab")
    except OSError as exc:
        raise SystemExit(f"{path} is a link or cannot be opened ({exc.strerror}): refusing to write {what} there") from None
    with handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise SystemExit(f"{path} is not a plain file: refusing to write {what} there")
        yield handle


def run_docker(argv: list[str], name: str, timeout: int, env: dict[str, str], log: Path,
               max_bytes: int = 20_000_000, workspace: Path | None = None, workspace_growth: int = 0,
               workspace_baseline: tuple[int, int] | None = None, workspace_files: int = 0) -> tuple[int, str]:
    """Run a container; return the exit code and the last OUTPUT_TAIL_BYTES of its output.

    The output goes to `log` only until the file is `max_bytes` long (a looping model or test can print gigabytes for the
    whole timeout, and several containers of one gate run share a file: the allowance is the file's, not each call's); the
    rest is read and dropped so the container never blocks on a full pipe, and the tail is kept in memory.

    `workspace` is the host directory bind-mounted into the container as /work: neither the tmpfs nor the memory limit
    bounds what is written there, so the container is stopped (exit 125) once the directory has grown by more than
    `workspace_growth` bytes, or by more than `workspace_files` files, links and directories (an inode costs even when the
    bytes are none), since it started, or since `workspace_baseline` (bytes, entries) when the caller gives one: containers
    that reuse one workspace one after another (the gate commands) share a single allowance instead of a fresh one each."""
    network = network_of(argv)
    if network != "none":
        # Whatever a model-written command does, the only thing between it and the LAN is the egress rules.
        problem = egress_problem(network or "docker's default bridge", live=True)
        if problem:
            raise SystemExit(f"{name} not started: {problem}")
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    tracked = bool(workspace and (workspace_growth > 0 or workspace_files > 0))
    base_bytes, base_entries = 0, 0
    if tracked:
        base_bytes, base_entries = workspace_baseline if workspace_baseline is not None else workspace_usage(workspace)[:2]
    tail = bytearray()
    written = 0

    def pump(pipe, sink) -> None:
        nonlocal written
        truncated = False
        for chunk in iter(lambda: pipe.read1(65536), b""):
            tail.extend(chunk)
            if len(tail) > 2 * OUTPUT_TAIL_BYTES:
                del tail[:len(tail) - OUTPUT_TAIL_BYTES]
            room = max_bytes - written
            if room > 0:
                sink.write(chunk[:room])
                written += min(len(chunk), room)
            if len(chunk) > room and not truncated:
                truncated = True
                sink.write(f"\n[team] output truncated at {max_bytes} bytes; the end of it is kept in memory\n".encode())
        sink.flush()

    stopped: list[str] = []
    finished = threading.Event()

    def over_allowance() -> str | None:
        """Why the workspace is past its allowance, or None."""
        used, entries, over = workspace_usage(workspace, base_entries + workspace_files if workspace_files > 0 else None)
        if workspace_files > 0 and (over or entries - base_entries > workspace_files):
            return f"\n[team] workspace grew by more than {workspace_files} files (limit {workspace_files}): container stopped\n"
        if workspace_growth > 0 and used - base_bytes > workspace_growth:
            return f"\n[team] workspace grew by {used - base_bytes} bytes (limit {workspace_growth}): container stopped\n"
        return None

    def guard(proc) -> None:
        while not finished.wait(WORKSPACE_POLL_S):
            why = over_allowance()
            if why:
                stopped.append(why)
                subprocess.run(["docker", "kill", name], capture_output=True)
                proc.kill()
                return

    with open_for_append(log, f"the output of {name}") as sink:
        written = sink.tell()
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        reader = threading.Thread(target=pump, args=(proc.stdout, sink), daemon=True)
        reader.start()
        watcher = None
        if tracked:
            watcher = threading.Thread(target=guard, args=(proc,), daemon=True)
            watcher.start()
        note = b""
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            rc = 124
            note = f"\n[team] timed out after {timeout}s\n".encode()
        finally:
            finished.set()
        reader.join(timeout=30)
        if watcher:
            watcher.join()
            # The guard looks every WORKSPACE_POLL_S: a container can write past the limit and exit between two looks, and
            # finishing wakes the guard only to leave. So the last measurement is taken here, before the exit is accepted.
            why = None if stopped else over_allowance()
            if why:
                stopped.append(why)
        if stopped:
            rc, note = 125, stopped[0].encode()
        if note:
            sink.write(note)
            tail.extend(note)
    return rc, ANSI_RE.sub("", bytes(tail[-OUTPUT_TAIL_BYTES:]).decode("utf-8", "replace"))


def stage_file(src: Path, dst: Path) -> None:
    """Copy one handoff file for a worker.

    The feature directory is group-writable, so `src` is whatever the lead left there. A link to workers.env mounted as is would
    have Docker, which follows it as root, bind the provider keys into a networked container. So the file is opened without
    following links, must be a plain file of a sane size, and is copied; the copy is what gets mounted."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)  # NONBLOCK: a named pipe must not hang us
    except OSError as exc:
        raise SystemExit(f"handoff file {src} is a link or cannot be read ({exc.strerror}): refusing to mount it") from None
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise SystemExit(f"handoff file {src} is not a plain file: refusing to mount it")
        copied, too_big = 0, False
        with os.fdopen(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                copied += len(chunk)
                if copied > HANDOFF_FILE_MAX_BYTES:
                    too_big = True
                    break
                target.write(chunk)
    if too_big:
        dst.unlink()
        raise SystemExit(f"handoff file {src} is larger than {HANDOFF_FILE_MAX_BYTES} bytes: refusing to mount it")


@contextlib.contextmanager
def staged_mounts(f: Feature, mounts: dict[str, Path]):
    """The handoff files as copies in a directory made for this call, in the team home (which the lead's login cannot write).
    Their names are fixed strings; the directories they come from must not be links either."""
    for directory in {path.parent for path in mounts.values()}:
        if directory.is_symlink():
            raise SystemExit(f"{directory} is a link: refusing to mount handoff files from it")
    root = Path(tempfile.mkdtemp(prefix=".handoff-", dir=f.home))
    try:
        for name, path in mounts.items():
            stage_file(path, root / name)
        yield {name: root / name for name in mounts}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_worker(cfg, f: Feature, role: str, model: str, mounts: dict[str, Path], prompt: str,
               keys: dict[str, str]) -> tuple[int, str]:
    say(f"{role}: {model}")
    log = f.out / f"{role}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    write_file(log, f"# {role} {model} {now()}\n")
    with staged_mounts(f, mounts) as staged:
        argv = worker_argv(cfg, f, role, model, staged, prompt)
        return run_docker(argv, container_name(f, role), int(cfg["TEAM_WORKER_TIMEOUT"]),
                          worker_env(cfg, keys, model), log, int(cfg["TEAM_LOG_MAX_BYTES"]),
                          workspace=None if role == "reviewer" else f.repo,  # the reviewer's checkout is mounted read-only
                          workspace_growth=int(cfg["TEAM_WORKSPACE_GROWTH_BYTES"]),
                          workspace_files=int(cfg["TEAM_WORKSPACE_GROWTH_FILES"]))


def handoff_mounts(f: Feature, extra: dict[str, Path] | None = None) -> dict[str, Path]:
    mounts = {name: f.file(name) for name in MOUNTED}
    mounts.update(extra or {})
    return {name: path for name, path in mounts.items() if path.is_file()}


# --------------------------------------------------------------------- gates

def gate_argv(cfg: dict[str, str], work: Path, command: str, network: str, name: str) -> list[str]:
    return ["docker", "run", "--rm", "--name", name, "--network", network, *hardening(cfg),
            "-v", f"{work}:/work", "-w", "/work", cfg["TEAM_IMAGE"], "bash", "-lc", command]


def handoff_digest(f: Feature) -> str:
    """What the audit read besides the diff: the pack quotes spec.md and acceptance.md, which live outside the checkout."""
    digest = hashlib.sha256()
    for name in ("spec.md", "acceptance.md"):
        digest.update(f"{name}\0".encode() + read(f.file(name)).encode("utf-8") + b"\0")
    return digest.hexdigest()[:16]


def seals_dir(f: Feature) -> Path:
    return f.home / "seals"


def seal_path(f: Feature) -> Path:
    return seals_dir(f) / f"{f.id}.json"


def seals_problem(f: Feature, mode: bool = True) -> str | None:
    """Why `<home>/seals` cannot be trusted (None: it can, or it does not exist yet).

    Setup makes a home 2750, but a home from the time it was group-writable can still hold a link there into a directory
    the lead writes, or a directory the lead made. Reading a seal through either, or writing one, would let the lead forge
    what `team push` believes. The conductor makes the directory itself, so it must be a plain directory it owns."""
    seals = seals_dir(f)
    try:
        info = seals.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        return f"{seals} is not a plain directory"
    if info.st_uid != os.geteuid():
        return f"{seals} is not owned by the user running the conductor"
    if mode and info.st_mode & 0o022:
        return f"{seals} is writable by its group or by others"
    return None


def ensure_seals_dir(f: Feature, what: str) -> Path:
    """The seals directory, made if it is missing, once it is known to be a plain directory the conductor owns."""
    why = seals_problem(f, mode=False)  # the mode is put right below
    if why:
        raise SystemExit(f"cannot {what}: {why}. Run setup-vps-team.sh as root again, then rebuild the pack")
    seals = seals_dir(f)
    seals.mkdir(exist_ok=True)
    seals.chmod(0o750)
    return seals


def origin_path(f: Feature) -> Path:
    return seals_dir(f) / f"{f.id}.origin"


def write_origin(f: Feature, url: str) -> None:
    """Record, where the lead cannot write, the repository `team push` publishes to: the one the operator named in
    `team new --repo`. The clone's own .git/config is writable by whoever works in the feature directory, so it decides
    nothing."""
    seals = ensure_seals_dir(f, "record the destination")
    tmp = seals / f".{f.id}.origin.tmp"
    tmp.write_text(json.dumps({"repo": url, "recorded": now()}, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o640)
    tmp.replace(origin_path(f))


def sealed_origin(f: Feature) -> str:
    why = seals_problem(f)
    if why:
        raise SystemExit(f"{why}: run setup-vps-team.sh as root again before pushing")
    try:
        url = json.loads(origin_path(f).read_text(encoding="utf-8"))["repo"]
        if isinstance(url, str) and url:
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise SystemExit(f"no sealed destination for {f.id}: it was created before destinations were sealed, or the record is "
                     f"damaged. Create the feature again with `{team_lead().command} new`")


def push_sealed(f: Feature, url: str, source: str) -> None:
    """Push the commit `source` to `url` from a repository made for this call.

    The clone's .git/config is writable by the audit session, and push honours what is in it: remote.origin.pushurl, url.*.
    insteadOf, core.sshCommand, a credential helper, hooks. So that file is never read: the objects are borrowed through
    `alternates` into an empty bare repository with a config of its own, and the destination is the sealed one."""
    root = Path(tempfile.mkdtemp(prefix=".push-", dir=f.home))
    try:
        git_dir = root / "push.git"
        env = {**base_env(), "GIT_TERMINAL_PROMPT": "0"}
        made = subprocess.run(["git", *GIT_SAFE, "init", "--bare", "-q", "--template=", str(git_dir)], cwd=root, env=env,
                              capture_output=True, text=True)
        if made.returncode:
            raise SystemExit(f"could not prepare the push: {made.stderr.strip()}")
        (git_dir / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (git_dir / "objects" / "info" / "alternates").write_text(f"{f.repo / '.git' / 'objects'}\n", encoding="utf-8")
        pushed = subprocess.run(["git", *GIT_SAFE, f"--git-dir={git_dir}", "push", "--no-verify", "--", url,
                                 f"{source}:refs/heads/{f.branch}"], cwd=root, env=env, capture_output=True, text=True)
        if pushed.returncode:
            raise SystemExit(f"git push failed: {pushed.stderr.strip()}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_seal(f: Feature, pack: Path) -> None:
    """Record, outside the feature directory, what the audit was shown. A lead that obeys an instruction hidden in the pack
    can rewrite everything inside its own workspace (the repository, state.json, gates.log); the directory it cannot write
    to is the only thing `team push` believes. The conductor creates it 0750: the group (the lead's login) can read, not write."""
    seals = ensure_seals_dir(f, "seal the audit")
    seal = {"pack_head": head(f.repo), "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
            "handoff": handoff_digest(f), "sealed": now()}
    tmp = seals / f".{f.id}.tmp"
    tmp.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o640)
    tmp.replace(seal_path(f))


def seal_problem(f: Feature) -> tuple[dict | None, str | None]:
    """(the seal, None) when push may rely on it, else (None, why not)."""
    why = seals_problem(f)
    if why:
        return None, f"{why}: run setup-vps-team.sh as root again, rebuild the pack with `{team_lead().command} pack {f.id}` and audit again"
    try:
        seal = json.loads(seal_path(f).read_text(encoding="utf-8"))
        pack = f.file("audit-pack.md").read_bytes()
    except (OSError, ValueError):
        return None, f"no seal for the audit pack: rebuild it with `{team_lead().command} pack {f.id}` and audit again"
    if seal.get("pack_head") != head(f.repo):
        return None, "HEAD changed after the audit pack was sealed: rebuild the pack and audit again"
    if seal.get("pack_sha256") != hashlib.sha256(pack).hexdigest():
        return None, "audit-pack.md changed after it was sealed: rebuild the pack and audit again"
    if seal.get("handoff") != handoff_digest(f):
        return None, "spec.md or acceptance.md changed after the audit pack was sealed: rebuild the pack and audit again"
    return seal, None


def commands_digest(commands: list[str]) -> str:
    """What identifies a gate suite: the commands, not the prose around them in acceptance.md."""
    return hashlib.sha256(json.dumps(commands).encode("utf-8")).hexdigest()[:12]


def run_gates(f: Feature, cfg: dict[str, str]) -> bool:
    """Run acceptance.md's commands on a clean checkout of HEAD, in a container
    with no key and (by default) no network. Writes gates.log."""
    commands, broken = parse_acceptance(read(f.file("acceptance.md")))
    lines = [f"# gates {f.id} @ {head(f.repo)[:12]} acceptance:{commands_digest(commands)} {now()}"]
    if broken:  # the suite is not the one that was written: it cannot pass, and nothing is started
        lines += [f"## FAIL acceptance.md: {broken}", f"RESULT: FAIL (0/{len(commands)} passed)"]
        write_file(f.file("gates.log"), "\n".join(lines) + "\n")
        say(f"gates: {lines[-1]}")
        return False
    timeout = int(cfg["TEAM_GATE_TIMEOUT"])
    name = container_name(f, "gates")
    passed = 0
    tmp = Path(tempfile.mkdtemp(prefix="gates-", dir=f.out))
    raw = f.out / "gates-raw.log"
    write_file(raw, "")
    try:
        work = tmp / "work"
        export_head(f.repo, work)
        budget_from = workspace_usage(work)[:2]  # the setup and every command spend one allowance, measured from here
        setup = cfg["TEAM_GATES_SETUP"]
        if setup:
            # Setup installs what the (possibly model-edited) dependency files name,
            # so it gets the workers' egress-limited network, never the host's.
            rc, output = run_docker(gate_argv(cfg, work, setup, cfg["TEAM_WORKER_NETWORK"], name),
                                    name, timeout, base_env(), raw, int(cfg["TEAM_LOG_MAX_BYTES"]),
                                    workspace=work, workspace_growth=int(cfg["TEAM_WORKSPACE_GROWTH_BYTES"]),
                                    workspace_baseline=budget_from, workspace_files=int(cfg["TEAM_WORKSPACE_GROWTH_FILES"]))
            lines += [f"## SETUP exit {rc}: {setup}", tail_text(output, 20)]
            if rc:
                commands = []
        for command in commands:
            started = time.monotonic()
            rc, output = run_docker(gate_argv(cfg, work, command, cfg["TEAM_GATES_NETWORK"], name),
                                    name, timeout, base_env(), raw, int(cfg["TEAM_LOG_MAX_BYTES"]),
                                    workspace=work, workspace_growth=int(cfg["TEAM_WORKSPACE_GROWTH_BYTES"]),
                                    workspace_baseline=budget_from, workspace_files=int(cfg["TEAM_WORKSPACE_GROWTH_FILES"]))
            passed += rc == 0
            lines += [f"## {'PASS' if rc == 0 else 'FAIL'} exit {rc} ({time.monotonic() - started:.1f}s): {command}",
                      tail_text(output, 40)]
    finally:
        # Toolchain caches inside the checkout can be read-only; never let
        # cleanup stop gates.log from being written.
        subprocess.run(["chmod", "-R", "u+rwX", str(tmp)], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    total = len(acceptance_commands(read(f.file("acceptance.md"))))
    ok = total > 0 and passed == total
    lines.append(f"RESULT: {'PASS' if ok else 'FAIL'} ({passed}/{total} passed)")
    write_file(f.file("gates.log"), "\n".join(lines) + "\n")
    say(f"gates: {lines[-1]}")
    return ok


# --------------------------------------------------------------------- roles

def run_tester(f: Feature, cfg, keys, state: dict) -> bool:
    drop_round_warnings(state, "tester")
    prompt = render(shipped(PROMPTS, "tester.md"), id=f.id)
    for model in models_for(cfg, "tester"):
        rc, _ = run_worker(cfg, f, "tester", model, handoff_mounts(f), prompt, keys)
        if rc == 0 and commit_all(f.repo, f"test({f.id}): acceptance tests [{model}]", merge_base(f, state),
                                  int(cfg["TEAM_MIN_FREE_BYTES"])):
            state["tester_commit"] = head(f.repo)
            state["tester_model"] = model
            if run_gates(f, cfg):
                warn(state, "acceptance commands already pass after the tester stage: "
                            "the new tests may not exercise the feature", round="tester")
            return True
        discard(f.repo)
        say(f"tester: {model} produced no usable tests (exit {rc})")
    return False


def run_coder(f: Feature, cfg, keys, state: dict, feedback: str | None, attempts: int | None = None) -> bool:
    models = models_for(cfg, "coder")
    original = feedback
    last_gates = None
    last_error = ""
    for attempt in range(attempts or int(cfg["TEAM_CODER_ATTEMPTS"])):
        model = models[attempt % len(models)]
        if feedback:
            note = f.out / "feedback.md"
            write_file(note, feedback)
            prompt, mounts = render(shipped(PROMPTS, "fix.md"), id=f.id), handoff_mounts(f, {"feedback.md": note})
        else:
            prompt, mounts = render(shipped(PROMPTS, "coder.md"), id=f.id), handoff_mounts(f)
        rc, output = run_worker(cfg, f, "coder", model, mounts, prompt, keys)
        if rc != 0:
            discard(f.repo)
            last_error = last_line(output)
            say(f"coder: {model} failed (exit {rc}): {last_error}")
            continue
        commit_all(f.repo, f"feat({f.id}): attempt {attempt + 1} [{model}]", merge_base(f, state),
                   int(cfg["TEAM_MIN_FREE_BYTES"]))
        if run_gates(f, cfg):
            state["coder_model"] = model
            state.pop("gate_feedback", None)
            return True
        last_gates = ("The acceptance commands still fail. Fix the implementation, not the tests.\n\n"
                      + tail(f.file("gates.log"), 80))
        feedback = (f"{original}\n\n---\n\n" if original else "") + last_gates
    if last_gates:
        state["gate_feedback"] = last_gates  # a resumed `team run` starts from it
    # No attempt reached the gates: every model run itself failed (quota, provider
    # error). Say so, with the model's own last words, rather than blaming the code.
    state["coder_error"] = "" if last_gates else last_error
    return False


def extract_review(output: str) -> str | None:
    start = output.rfind(REVIEW_START)
    if start < 0:
        return None
    end = output.find(REVIEW_END, start)
    body = output[start + len(REVIEW_START): end if end >= 0 else None].strip()
    return "\n".join(body.splitlines()[:REVIEW_MAX_LINES]) or None


def blockers(review: str) -> list[str]:
    found = []
    for row in review.splitlines():
        match = re.match(r"(?i)blocker[:\s]+(.*)", row.strip().lstrip("-*• "))
        if match and match.group(1).strip().rstrip(".").lower() not in ("", "none", "n/a", "-"):
            found.append(row)
    return found


def drop_round_warnings(state: dict, round: str) -> None:
    """A warning a stage raised describes that round (no reviewer answered, a fix not re-reviewed, tests that already pass).
    A new round of the stage replaces it; warnings from other stages still apply and stay."""
    stale = state.pop(f"{round}_warnings", [])
    state["warnings"] = [w for w in state.get("warnings", []) if w not in stale]


def run_reviewer(f: Feature, cfg, keys, state: dict) -> str | None:
    """One review round, from the pipeline or from `team work reviewer`: it replaces the last round's review and warnings."""
    drop_round_warnings(state, "review")
    diff = f.out / "diff.patch"
    limit = int(cfg["TEAM_PACK_MAX_BYTES"])  # a diff past the pack's size is refused there anyway; the reviewer reads this much
    text, cut = git_capped(f.repo, *readable_diff(f.repo), f"{merge_base(f, state)}..HEAD", limit=limit)
    if cut:
        text += CUT_NOTE.format(limit=limit)
        warn(state, f"the reviewer read only the first {limit} bytes of the diff", round="review")
    write_file(diff, text)
    mounts = handoff_mounts(f, {"diff.patch": diff, "gates.log": f.file("gates.log")})
    prompt = render(shipped(PROMPTS, "reviewer.md"), id=f.id)
    # A review belongs to the HEAD it read. If every reviewer fails on a rerun, the pack must say "none", not carry
    # the last run's review (blockers or a clean bill) for code that has since changed.
    f.file("prereview.md").unlink(missing_ok=True)
    state.pop("reviewer_model", None)
    for model in models_for(cfg, "reviewer"):
        rc, output = run_worker(cfg, f, "reviewer", model, mounts, prompt, keys)
        review = extract_review(output) if rc == 0 else None
        if review:
            write_file(f.file("prereview.md"), f"<!-- reviewer: {model} -->\n{review}\n")
            state["reviewer_model"] = model
            state["reviewed_head"] = head(f.repo)
            return review
        say(f"reviewer: {model} returned no review block (exit {rc})")
    warn(state, "no reviewer model returned a review", round="review")
    return None


# ---------------------------------------------------------------------- pack

def diff_of(repo: Path, revs: str, paths: list[str]) -> str:
    """The readable diff of exactly these paths, ARG_BATCH at a time."""
    return diff_capped(repo, revs, paths, None)[0]


def diff_capped(repo: Path, revs: str, paths: list[str], limit: int | None) -> tuple[str, bool]:
    """diff_of, stopping at `limit` bytes (None: no limit). The flag says it stopped."""
    batches = (paths[i:i + ARG_BATCH] for i in range(0, len(paths), ARG_BATCH))
    parts: list[str] = []
    room = limit
    for batch in batches:
        args = (*readable_diff(repo), revs, "--", *(f":(literal){path}" for path in batch))
        if room is None:
            parts.append(git(repo, *args))
            continue
        text, cut = git_capped(repo, *args, limit=room)
        parts.append(text)
        room -= len(text.encode("utf-8"))
        if cut:
            return "".join(parts), True
    return "".join(parts), False


def binary_paths(repo: Path, revs: str) -> list[str]:
    """Paths the Diff shows only as `Binary files ... differ`. readable_diff
    ignores attributes, so this is git's content test, and one NUL byte passes
    it: a worker can hide a source file that way, so the auditor gets the list."""
    records = git_listing(repo, *readable_diff(repo), "--numstat", "-z", "--no-renames", revs).split("\0")
    return [record.split("\t", 2)[2] for record in records if record.startswith("-\t-\t")]


def test_paths_changed(f: Feature, tester_commit: str) -> list[str]:
    """Test files touched after the tester stage: where a weak model 'fixes' a
    failing test by weakening it."""
    # --no-renames: with rename detection git reports only the new name, so moving a tester file to a path that is
    # neither in `written` nor a test path would hide the change from the auditor.
    written = set(git_paths(f.repo, "show", "-z", "--name-only", "--no-renames", "--format=", tester_commit))
    changed = git_paths(f.repo, "diff", "-z", "--name-only", "--no-renames", f"{tester_commit}..HEAD")
    return [path for path in changed if path in written or TEST_PATH_RE.search(path)]


GATES_HEAD_RE = re.compile(r"# gates \S+ @ ([0-9a-f]{12}) acceptance:([0-9a-f]{12})")


def gates_problem(f: Feature) -> str | None:
    """Why gates.log is no verdict on what would be audited or published: it ran on another commit or other acceptance
    commands, or it did not pass."""
    log = read(f.file("gates.log"))
    ran = GATES_HEAD_RE.match(log)
    commands = commands_digest(acceptance_commands(read(f.file("acceptance.md"))))
    if not ran:
        return f"gates.log has no run on record: run `{team_lead().command} gates {f.id}` first"
    if ran[1] != head(f.repo)[:12]:
        return f"gates.log is for {ran[1]}, HEAD is {head(f.repo)[:12]}: run `{team_lead().command} gates {f.id}` first"
    if ran[2] != commands:
        return (f"gates.log ran other acceptance commands than acceptance.md has now: "
                f"run `{team_lead().command} gates {f.id}` first")
    result = next((row for row in reversed(log.splitlines()) if row.startswith("RESULT")), "")
    if not result.startswith("RESULT: PASS"):
        return f"the gates did not pass ({result or 'no result'}): fix the code and run `{team_lead().command} gates {f.id}`"
    return None


def build_pack(f: Feature, cfg, state: dict, force: bool = False) -> int:
    pack = f.file("audit-pack.md")
    # The pack quotes gates.log as the verdict on this code. It is one only if the gates ran on this HEAD with these
    # commands and passed; --force lifts the size limit, never this.
    problem = gates_problem(f)
    if problem:
        pack.unlink(missing_ok=True)
        seal_path(f).unlink(missing_ok=True)
        print(problem, file=sys.stderr)
        return 1
    base = merge_base(f, state)
    sections = [f"# Audit pack {f.id}",
                f"Branch {f.branch} @ {head(f.repo)[:12]} vs {state.get('base', 'main')} ({base[:12]})", ""]

    def add(title: str, body: str) -> None:
        sections.extend([f"## {title}", body.rstrip() or "(none)", ""])

    limit, max_bytes = int(cfg["TEAM_PACK_MAX_LINES"]), int(cfg["TEAM_PACK_MAX_BYTES"])
    # A diff past the byte ceiling makes the pack too big whatever else it holds, so it is read only that far (or, for --force,
    # up to PACK_FORCE_DIFF_BYTES): a worker's several large files must not be held whole to be told they are too many.
    diff_limit = PACK_FORCE_DIFF_BYTES if force else max_bytes
    cut_anywhere = False

    add("Spec", read(f.file("spec.md")))
    add("Acceptance", read(f.file("acceptance.md")))
    add("Gates", tail(f.file("gates.log"), 60))
    add("Pipeline warnings", "\n".join(f"- {w}" for w in state.get("warnings", [])))
    review = read(f.file("prereview.md"))
    if review.strip() and state.get("reviewed_head") != head(f.repo):
        review = (f"STALE: this review read commit {(state.get('reviewed_head') or 'unknown')[:12]} and HEAD is "
                  f"{head(f.repo)[:12]}: it describes older code and says nothing about the commits since.\n\n" + review)
    add("Pre-review", review)
    tester = state.get("tester_commit")
    if tester:
        paths = test_paths_changed(f, tester)
        shown, cut = diff_capped(f.repo, f"{tester}..HEAD", paths, diff_limit) if paths else ("", False)
        cut_anywhere = cut_anywhere or cut
        body = "```diff\n" + shown.rstrip() + (CUT_NOTE.format(limit=diff_limit) if cut else "") + "\n```" if paths else ""
        add("Test files changed after the tester commit", body)
    else:
        add("Test files changed after the tester commit", "UNKNOWN: no tester commit recorded")
    touched = [p for p in git_listing(f.repo, "diff", "-z", "--name-only", "--no-renames", f"{base}..HEAD").split("\0") if p]
    add("Sensitive paths changed (CI on this VPS, agent instructions): BLOCK unless the spec asks for it",
        "\n".join(p for p in touched if SENSITIVE_PATH_RE.search(p)))
    add("Lockfiles changed (their diff is in Diff below: check every new, swapped or re-resolved package, URL "
        "and integrity hash; CI installs from them on this VPS)",
        "\n".join(p for p in touched if any(Path(p).match(name) for name in LOCKFILES)))
    add("Binary files changed (their contents are NOT in this pack, and one NUL byte makes any file binary, "
        "source included): BLOCK unless the spec asks for each one", "\n".join(binary_paths(f.repo, f"{base}..HEAD")))
    stat_text, stat_cut = git_capped(f.repo, *readable_diff(f.repo), "--stat", f"{base}..HEAD", limit=diff_limit)
    cut_anywhere = cut_anywhere or stat_cut
    add("Diffstat", stat_text + (CUT_NOTE.format(limit=diff_limit) if stat_cut else ""))
    shown, cut = git_capped(f.repo, *readable_diff(f.repo), f"{base}..HEAD", limit=diff_limit)
    cut_anywhere = cut_anywhere or cut
    add("Diff", "```diff\n" + shown.rstrip() + (CUT_NOTE.format(limit=diff_limit) if cut else "") + "\n```")
    text = "\n".join(sections)
    lines = text.count("\n")
    size = len(text.encode("utf-8"))
    if cut_anywhere and force:
        # --force lifts the size limit, not the completeness of what the auditor reads: an approval of this pack would cover
        # changes the auditor never saw.
        pack.unlink(missing_ok=True)
        seal_path(f).unlink(missing_ok=True)
        print(f"the diff is longer than {diff_limit} bytes, the most a pack can quote even with --force: it would be cut and "
              f"sealed incomplete. Split the feature", file=sys.stderr)
        return 1
    # Bytes as well as lines: a minified or generated file is one line however large it is.
    if (lines > limit or size > max_bytes) and not force:
        pack.unlink(missing_ok=True)
        print(f"audit pack would be {'at least ' if cut_anywhere else ''}{lines} lines and {size} bytes "
              f"(limits {limit} lines, {max_bytes} bytes): "
              f"split the feature, or `{team_lead().command} pack {f.id} --force`", file=sys.stderr)
        return 1
    write_file(pack, text)
    write_seal(f, pack)
    state["pack_head"] = head(f.repo)
    f.save_state(state)
    say(f"audit pack: {pack} ({lines} lines)")
    return 0


# ------------------------------------------------------------------ pipeline

@contextlib.contextmanager
def run_lock(home: Path):
    """One pipeline at a time: the VPS is small and shared with CI jobs."""
    handle = open(lock_path(home), "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit(f"another pipeline is running ({team_lead().command} status)")
    try:
        yield
    finally:
        handle.close()


def lock_busy(home: Path) -> bool:
    """Read-only probe: `team status` runs as the admin and must not create the
    lock file with the admin's umask (user team could not open it after)."""
    path = lock_path(home)
    if not path.is_file():
        return False
    with open(path) as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def blocked(f: Feature, state: dict, reason: str) -> int:
    state["stage"] = f"blocked: {reason}"
    f.save_state(state)
    say(f"BLOCKED: {reason}. Fix it (team.env models, spec) and rerun `{team_lead().command} run {f.id}`.")
    return 2


def pipeline(f: Feature, cfg, keys, state: dict, start: str, feedback: str | None) -> int:
    for index, stage in enumerate(STAGES[STAGES.index(start):], STAGES.index(start)):
        problem = None if stage == "pack" else egress_problem(cfg["TEAM_WORKER_NETWORK"], live=True)
        if problem:
            state["next"] = stage
            return blocked(f, state, problem)
        state["stage"] = f"running: {stage}"
        state["next"] = stage
        f.save_state(state)
        if stage == "tester":
            if not run_tester(f, cfg, keys, state):
                return blocked(f, state, "no tester model produced tests")
        elif stage == "coder":
            if not run_coder(f, cfg, keys, state, feedback):
                error = state.pop("coder_error", "")
                return blocked(f, state, f"every coder model run failed, last error: {error}" if error
                               else "acceptance commands still fail after every coder attempt")
            state.pop("pending_feedback", None)
        elif stage == "review":
            review = run_reviewer(f, cfg, keys, state)
            if review is not None and blockers(review):
                before = head(f.repo)
                fix = "A reviewer found blockers. Fix them; change nothing else.\n\n" + review
                passed = run_coder(f, cfg, keys, state, fix, attempts=1)
                if passed and head(f.repo) != before:
                    warn(state, "pre-review blockers were addressed by a fix commit that was not re-reviewed", round="review")
                else:
                    # A coder that exits cleanly without changing a file leaves the gates passing: that is no fix.
                    git(f.repo, "reset", "-q", "--hard", before)
                    state.pop("gate_feedback", None)  # belongs to the reverted fix, not to HEAD
                    run_gates(f, cfg)
                    warn(state, f"{len(blockers(review))} pre-review blocker(s) stand: " +
                         ("the fix attempt made no commit" if passed else "the fix attempt broke the gates and was reverted"),
                         round="review")
        elif stage == "pack":
            if build_pack(f, cfg, state):
                return blocked(f, state, "audit pack not built: over the size limit, or the gates did not run on this commit")
        state["next"] = STAGES[index + 1] if index + 1 < len(STAGES) else "done"
        f.save_state(state)
    state["stage"] = "ready for audit"
    f.save_state(state)
    lead = team_lead()
    say(f"done. Audit: cd {f.dir} && {lead.cli}   (prompt: {lead.command} prompt {lead.name}-audit {f.id})")
    return 0


# ------------------------------------------------------------------ commands

def cmd_new(args, home: Path, cfg) -> int:
    lead = team_lead()
    f = Feature(home, args.id)
    if f.dir.exists():
        raise SystemExit(f"{f.dir} already exists")
    base = args.base or cfg["TEAM_BASE"]
    f.out.mkdir(parents=True)
    try:
        clone = subprocess.run(["git", *GIT_SAFE, "clone", "-q", "--branch", base, "--", args.repo, str(f.repo)])
        if clone.returncode:
            raise SystemExit(f"could not clone {args.repo} at {base}")
        git(f.repo, "checkout", "-q", "-b", f.branch)
        local = Path(args.repo)  # a path is made absolute: the push runs from another directory
        write_origin(f, str(local.resolve()) if local.exists() else args.repo)
    except SystemExit:
        shutil.rmtree(f.dir, ignore_errors=True)
        raise
    git(f.repo, "config", "user.name", cfg["TEAM_GIT_NAME"])
    git(f.repo, "config", "user.email", cfg["TEAM_GIT_EMAIL"])
    for name in HANDOFF:
        f.file(name).write_text(render(shipped(TEMPLATES, name), id=f.id, repo=args.repo, base=base, lead=lead.name,
                                       title=lead.title, team=lead.command), encoding="utf-8")
    write_file(f.file("repo-map.txt"), repo_map(f.repo, int(cfg["TEAM_MAP_MAX_LINES"])))
    f.save_state({"base": base, "repo": args.repo, "stage": "spec", "next": "tester"})
    print(f"created {f.dir}\n"
          f"1. write {f.file('request.md')}\n"
          f"2. cd {f.dir} && {lead.cli}   (prompt: {lead.command} prompt {lead.name}-spec {f.id})\n"
          f"3. {lead.command} check-spec {f.id} && {lead.command} run {f.id} --detach")
    return 0


def cmd_map(args, home, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    write_file(f.file("repo-map.txt"), repo_map(f.repo, int(cfg["TEAM_MAP_MAX_LINES"])))
    print(f.file("repo-map.txt"))
    return 0


def cmd_check_spec(args, home, cfg) -> int:
    problems = check_spec(Feature(home, args.id))
    for problem in problems:
        print(f"spec: {problem}")
    if not problems:
        print("spec OK")
    return 1 if problems else 0


def cmd_run(args, home: Path, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    problems = check_spec(f)
    if problems:
        print("\n".join(f"spec: {p}" for p in problems), file=sys.stderr)
        return 1
    for role in ("tester", "coder", "reviewer"):
        if not models_for(cfg, role):
            raise SystemExit(f"TEAM_MODELS_{role.upper()} is empty in {home / 'team.env'}")
    if args.from_ == "verdict":
        verdict_feedback(f, f.load_state(), args.force)
    if args.detach:
        if lock_busy(home):
            raise SystemExit(f"another pipeline is running ({team_lead().command} status)")
        cmd = [sys.executable, str(Path(__file__).resolve()), "run", f.id]
        cmd += (["--from", args.from_] if args.from_ else []) + (["--force"] if args.force else [])
        with open_for_append(f.out / "run.log", "the output of the detached run") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        print(f"started {f.id} (pid {proc.pid}); follow: tail -f {f.out / 'run.log'}  or  {team_lead().command} status {f.id}")
        return 0
    with run_lock(home):
        state = f.load_state()
        start = args.from_ or state.get("next", "tester")
        if start == "verdict":
            state["pending_feedback"] = verdict_feedback(f, state, args.force)
            state["audit_rounds"] = state.get("audit_rounds", 0) + 1
            # The audited verdict is spent: keep it, but out of the way, so a stale
            # verdict can never be read as the verdict on the next pack.
            f.file("verdict.md").replace(f.out / f"verdict-round-{state['audit_rounds']}.md")
            start = "coder"
        feedback = "\n\n---\n\n".join(
            text for text in (state.get("pending_feedback"), state.get("gate_feedback")) if text) or None
        if start == "done":
            say("pipeline already finished; use --from tester|coder|review|pack|verdict")
            return 0
        return pipeline(f, cfg, load_keys(home), state, start, feedback)


def verdict_feedback(f: Feature, state: dict, force: bool) -> str:
    verdict = f.file("verdict.md")
    if verdict_of(read(verdict)) != "BLOCK":
        raise SystemExit(f"{verdict} has no 'VERDICT: BLOCK' line to fix")
    if state.get("audit_rounds", 0) >= 1 and not force:
        raise SystemExit(f"the one extra audit round is used up: decide in {team_lead().title}, or pass --force")
    return "The auditor blocked this change. Fix every BLOCKER below.\n\n" + read(verdict)


def cmd_work(args, home, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    if args.model:
        cfg = {**cfg, f"TEAM_MODELS_{args.role.upper()}": args.model}
    keys = load_keys(home)
    with run_lock(home):
        state = f.load_state()
        if args.role == "tester":
            ok = run_tester(f, cfg, keys, state)
        elif args.role == "coder":
            ok = run_coder(f, cfg, keys, state, None, attempts=1)
        else:
            ok = run_reviewer(f, cfg, keys, state) is not None
        f.save_state(state)
    return 0 if ok else 1


def cmd_gates(args, home, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    with run_lock(home):  # gates.log is also written by a running pipeline
        return 0 if run_gates(f, cfg) else 1


def cmd_pack(args, home, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    with run_lock(home):  # audit-pack.md and state.json are also written by a running pipeline
        return build_pack(f, cfg, f.load_state(), force=args.force)


CONFIRM_TTY = "/dev/tty"


def confirm_force(f: Feature) -> None:
    """`push --force` skips the verdict, seal and gate checks, so it is for a person: it asks on the controlling terminal,
    which a script or an agent's shell does not have. A speed bump for one that opens a pseudo-terminal of its own, not a
    boundary: the account the audit runs under is (docs/vps-team.md)."""
    try:
        answer, prompt = open(CONFIRM_TTY, "r"), open(CONFIRM_TTY, "a")
    except OSError:
        raise SystemExit("push --force skips the verdict, seal and gate checks, so it needs a person at a terminal "
                         f"(it asks for confirmation on {CONFIRM_TTY}); a script or an agent's shell cannot give one")
    with answer, prompt:
        prompt.write(f"push {head(f.repo)[:12]} of {f.id} to {f.branch} WITHOUT the verdict, seal and gate checks? "
                     "Type the feature id to confirm: ")
        prompt.flush()
        if answer.readline().strip() != f.id:
            raise SystemExit("not confirmed: nothing was pushed")


def cmd_push(args, home, cfg) -> int:
    f = Feature(home, args.id)
    f.require()
    if args.force:
        confirm_force(f)  # before the lock: a person's answer must not hold up a running pipeline
    with run_lock(home):  # no pipeline may move the branch between the checks and the push
        state = f.load_state()
        source = head(f.repo)
        if not args.force:
            if verdict_of(read(f.file("verdict.md"))) != "APPROVE":
                raise SystemExit("verdict.md has no 'VERDICT: APPROVE' line: audit first")
            seal, why = seal_problem(f)  # what push believes lives outside the lead's workspace, not in state.json
            if why:
                raise SystemExit(why)
            problem = gates_problem(f)  # a later gate run at this HEAD may have failed
            if problem:
                raise SystemExit(problem)
            if f.file("verdict.md").stat().st_mtime < f.file("audit-pack.md").stat().st_mtime:
                raise SystemExit("verdict.md is older than audit-pack.md: audit the current pack")
            source = seal["pack_head"]
        # An object id, never the branch name: the commit that was audited is
        # the one that is published, whatever the branch points at by now. And to the repository sealed when the feature was
        # made, with none of the clone's own configuration: that file is writable by the audit session.
        push_sealed(f, sealed_origin(f), source)
    print(f"pushed {source[:12]} to origin {f.branch}")
    return 0


def cmd_status(args, home: Path, cfg) -> int:
    work = home / "work"
    ids = [args.id] if args.id else sorted(p.name for p in work.iterdir() if p.is_dir()) if work.is_dir() else []
    if lock_busy(home):
        print("(a pipeline is running)")
    for fid in ids:
        f = Feature(home, fid)
        state = f.load_state()
        stage = state.get("stage", "?")
        if stage == "spec" and not check_spec(f):
            stage = f"spec ready: {team_lead().command} run"
        gates = next((row for row in reversed(read(f.file("gates.log")).splitlines()) if row.startswith("RESULT")), "-")
        verdict = verdict_of(read(f.file("verdict.md"))) or "-"
        print(f"{fid:<16} {stage:<34} {gates:<28} {verdict:<8} {state.get('updated', '')}")
    return 0


def cmd_prompt(args, home, cfg) -> int:
    f = Feature(home, args.id)
    lead = team_lead()
    print(render(shipped(PROMPTS, f"{PROMPT_FILES.get(args.name, args.name)}.md"), id=f.id, dir=f.dir, team=lead.command))
    return 0


def fetch_models(cfg, keys: dict[str, str], provider: str) -> list[str]:
    request = urllib.request.Request(MODELS_URLS[provider])
    name = key_env(cfg, provider)
    if name and keys.get(name):
        request.add_header("Authorization", f"Bearer {keys[name]}")
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    return sorted({str(m["id"]).removeprefix("models/") for m in data.get("data", []) if m.get("id")})


def opencode_catalog() -> dict[str, set[str]]:
    """The model ids OpenCode can resolve, per provider id."""
    request = urllib.request.Request(OPENCODE_CATALOG_URL, headers={"User-Agent": "team-doctor"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    return {provider: set(entry.get("models") or {}) for provider, entry in data.items() if isinstance(entry, dict)}


def cmd_models(args, home, cfg) -> int:
    if args.provider not in MODELS_URLS:
        raise SystemExit(f"unknown provider {args.provider!r}; known: {', '.join(MODELS_URLS)}")
    for model in fetch_models(cfg, load_keys(home), args.provider):
        if not args.free or model.endswith(":free"):
            print(f"{args.provider}/{model}")
    return 0


def smoke(cfg) -> tuple[list[str], list[str]]:
    """Prove the video image works under the real container limits: Chrome without capabilities
    and with a small /dev/shm, GSAP and audio with no network. A failed render is a problem; a
    failed narration is a note, because a team may supply its own voice files."""
    problems: list[str] = []
    notes: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="smoke-"))
    try:
        for label, command, found in (("render", SMOKE_RENDER, problems), ("narration", SMOKE_NARRATION, notes)):
            name = f"{team_lead().container}-doctor-{label}"
            rc, output = run_docker(gate_argv(cfg, work, command, "none", name), name,
                                    int(cfg["TEAM_GATE_TIMEOUT"]), base_env(), work / f"{label}.log",
                                    int(cfg["TEAM_LOG_MAX_BYTES"]), workspace=work,
                                    workspace_growth=int(cfg["TEAM_WORKSPACE_GROWTH_BYTES"]),
                                    workspace_files=int(cfg["TEAM_WORKSPACE_GROWTH_FILES"]))
            if rc:
                found.append(f"smoke {label} failed in {cfg['TEAM_IMAGE']} (exit {rc}): {last_line(output)}"
                             + ("" if label == "render" else
                                "; local Kokoro narration is unavailable, so narration must come from audio files"))
            else:
                notes.append(f"smoke {label}: OK")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return problems, notes


def doctor(home: Path, cfg, ping: bool, run_smoke: bool = False) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    found = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True,
                                                       text=True).stdout)
    if not found or (int(found[1]), int(found[2])) < (2, 40):
        problems.append("git 2.40 or newer is required (git --attr-source keeps .gitattributes from hiding diffs)")
    if not shutil.which("docker"):
        problems.append("docker is not installed")
    elif subprocess.run(["docker", "image", "inspect", cfg["TEAM_IMAGE"]], capture_output=True).returncode:
        problems.append(f"image {cfg['TEAM_IMAGE']} missing: docker build -t {cfg['TEAM_IMAGE']} {HERE}")
    if shutil.which("docker") and subprocess.run(["docker", "network", "inspect", cfg["TEAM_WORKER_NETWORK"]],
                                                 capture_output=True).returncode:
        problems.append(f"docker network {cfg['TEAM_WORKER_NETWORK']} missing: rerun setup-vps-team.sh")
    egress = egress_problem(cfg["TEAM_WORKER_NETWORK"])
    if egress:
        problems.append(egress)
    if team_lead().name == "codex" and not shutil.which("bwrap"):
        problems.append("bubblewrap (bwrap) is not installed: Codex's Linux sandbox cannot start, so codex-lead and its "
                        f"commands (even `{team_lead().command} check-spec`) would fail; sudo apt-get install bubblewrap "
                        "(setup-vps-team.sh --with-codex installs it)")
    secrets = home / "workers.env"
    if not secrets.is_file():
        problems.append(f"{secrets} missing (copy workers.env.example)")
    elif secrets.stat().st_mode & 0o077:
        problems.append(f"{secrets} must be mode 600 (chmod 600)")
    keys = load_keys(home) if secrets.is_file() else {}
    configured: dict[str, list[str]] = {}
    for role in ("tester", "coder", "reviewer"):
        models = models_for(cfg, role)
        if not models:
            problems.append(f"TEAM_MODELS_{role.upper()} is empty")
        for model in models:
            if "/" not in model or "<" in model or ">" in model:
                problems.append(f"{role}: {model!r} is not a provider/model id")
                continue
            configured.setdefault(provider_of(model), []).append(model)
            env_name = key_env(cfg, provider_of(model))
            if env_name is None:
                notes.append(f"{model}: unknown provider; set TEAM_KEY_{provider_of(model).upper()}=<ENV VAR>")
            elif not keys.get(env_name):
                problems.append(f"{model}: {env_name} is empty in workers.env")
    primary = {role: models_for(cfg, role)[0] for role in ("tester", "coder", "reviewer") if models_for(cfg, role)}
    for a, b in (("tester", "coder"), ("coder", "reviewer")):
        if a in primary and b in primary and family_of(primary[a]) == family_of(primary[b]):
            notes.append(f"{a} and {b} use the same model family ({family_of(primary[a])}): "
                         "the checker shares the writer's blind spots")
    if ping:
        for provider, models in sorted(configured.items()):
            if provider not in MODELS_URLS:
                notes.append(f"{provider}: no model listing known, not pinged")
                continue
            try:
                offered = set(fetch_models(cfg, keys, provider))
            except (urllib.error.URLError, OSError, ValueError) as exc:
                problems.append(f"{provider}: model listing failed ({exc})")
                continue
            for model in models:
                if model.split("/", 1)[1] not in offered:
                    problems.append(f"{model}: not offered by {provider} any more ({team_lead().command} models {provider})")
        if configured:
            try:
                catalog = opencode_catalog()
            except (urllib.error.URLError, OSError, ValueError) as exc:
                notes.append(f"OpenCode's model catalog (models.dev) not checked: {exc}")
            else:
                for provider, models in sorted(configured.items()):
                    for model in models:
                        if model.split("/", 1)[1] not in catalog.get(provider, set()):
                            problems.append(f"{model}: not in OpenCode's model catalog (models.dev) yet, so its "
                                            f"worker cannot start it; pick another ({team_lead().command} models {provider})")
    if team_lead().name == "video":
        if cfg["TEAM_IMAGE"] == VIDEO_IMAGE_DEFAULT:
            problems.append(f"TEAM_IMAGE is the code team's image: set TEAM_IMAGE=team-video-worker:latest in {home / 'team.env'} "
                            "(it has Chrome, ffmpeg and HyperFrames)")
        if not cfg["TEAM_WORKER_SHM"]:
            problems.append(f"TEAM_WORKER_SHM is empty: Chrome crashes on Docker's 64 MB /dev/shm; set 1g in {home / 'team.env'}")
        if cfg["TEAM_GATES_NETWORK"] != "none":
            notes.append("TEAM_GATES_NETWORK is not none: renders may reach a CDN the offline gates would reject")
    if run_smoke:
        if team_lead().name != "video":
            problems.append(f"--smoke is for {LEADS['video'].command}: the smoke project exists only in the video image")
        elif not problems:
            found, said = smoke(cfg)
            problems += found
            notes += said
        else:
            notes.append("smoke test skipped until the problems above are fixed")
    return problems, notes


def cmd_doctor(args, home, cfg) -> int:
    problems, notes = doctor(home, cfg, args.ping, args.smoke)
    for note in notes:
        print(f"note: {note}")
    for problem in problems:
        print(f"PROBLEM: {problem}")
    print("doctor: OK" if not problems else f"doctor: {len(problems)} problem(s)")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=team_lead().command, description=__doc__.split("\n\n")[0], allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, func, text: str, with_id: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=text, description=text, allow_abbrev=False)
        if with_id:
            p.add_argument("id")
        p.set_defaults(func=func)
        return p

    p = command("new", cmd_new, "clone a repo and create the handoff templates")
    p.add_argument("--repo", required=True, help="git URL or path the team user can clone")
    p.add_argument("--base", help="base branch (default TEAM_BASE)")
    command("map", cmd_map, "regenerate repo-map.txt")
    command("check-spec", cmd_check_spec, "validate request/spec/tasks/acceptance")
    p = command("run", cmd_run, "tester -> coder -> gates -> review -> pack")
    p.add_argument("--from", dest="from_", choices=STAGES + ("verdict",))
    p.add_argument("--detach", action="store_true", help="run in the background, log to out/run.log")
    p.add_argument("--force", action="store_true", help="allow a second extra audit round")
    p = command("work", cmd_work, "run one role once", with_id=False)
    p.add_argument("role", choices=("tester", "coder", "reviewer"))
    p.add_argument("id")
    p.add_argument("--model", help="provider/model, overrides team.env for this run")
    command("gates", cmd_gates, "run the acceptance commands on a clean checkout")
    p = command("pack", cmd_pack, "build audit-pack.md")
    p.add_argument("--force", action="store_true", help="ignore TEAM_PACK_MAX_LINES and TEAM_PACK_MAX_BYTES (never stale gates)")
    p = command("push", cmd_push, f"push {team_lead().command}/<id> after an APPROVE verdict")
    p.add_argument("--force", action="store_true")
    p = command("status", cmd_status, "show every feature's stage", with_id=False)
    p.add_argument("id", nargs="?")
    p = command("prompt", cmd_prompt, "print a role prompt", with_id=False)
    p.add_argument("name", choices=PROMPT_NAMES)
    p.add_argument("id")
    p = command("models", cmd_models, "list a provider's model ids", with_id=False)
    p.add_argument("provider")
    p.add_argument("--free", action="store_true", help="only ids ending in :free")
    p = command("doctor", cmd_doctor, "check docker, keys and model config", with_id=False)
    p.add_argument("--ping", action="store_true", help="also list each provider's models over the network")
    p.add_argument("--smoke", action="store_true",
                   help="video team: render a baked project and synthesise a sentence in the worker image")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = team_home()
    return args.func(args, home, load_config(home))


if __name__ == "__main__":
    sys.exit(main())
