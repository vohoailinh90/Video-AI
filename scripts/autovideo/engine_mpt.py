"""MoneyPrinterTurbo (MPT) as the rendering engine: one job in, one task out.

MPT keeps doing what it is good at: it downloads the stock clips, makes the voice with Edge TTS, writes the subtitles, mixes the
music and joins everything with MoviePy. This module only turns a `Job` into MPT's batch-manifest object, runs `cli.py` for it, and
reads the JSON summary MPT prints. MPT's keys stay in MPT's own config.toml; they are never copied, logged or put on a command line.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .pack import MUSIC_EXTENSIONS, NO_VOICE, Job

DEFAULT_HOME = Path("~/MoneyPrinterTurbo")
MUSIC_FOLDERS = ("storage/bgm", "resource/songs")  # where MPT looks for a custom music file, in this order
FILE_MISSING = "missing"  # what input_digests says for a file the job needs and MPT's directories do not have (never a hex digest)
FILE_UNREADABLE = "unreadable"  # ... and for one that is there but cannot be read (permissions, or it went away while it was being read)
SECRET_KEY = re.compile(r"key|token|secret|password", re.I)


class MptError(RuntimeError):
    pass


@dataclass(frozen=True)
class MptEnv:
    home: Path
    python: tuple[str, ...]


@dataclass
class EngineResult:
    ok: bool
    task_id: str | None = None
    failed_stage: str | None = None
    error: str | None = None
    video: Path | None = None
    audio: Path | None = None
    subtitle: Path | None = None
    task_dir: Path | None = None
    audio_seconds: float | None = None
    warnings: tuple = ()
    log_tail: str = ""


def locate(home: str | os.PathLike | None = None, python: str | None = None) -> MptEnv:
    """Find the MPT checkout (--mpt-home, $MPT_HOME, or ~/MoneyPrinterTurbo) and the Python that runs its cli.py."""
    path = Path(home or os.environ.get("MPT_HOME") or DEFAULT_HOME).expanduser().resolve()
    if not (path / "cli.py").is_file() or not (path / "app").is_dir():
        raise MptError(
            f"no MoneyPrinterTurbo checkout at {path} (cli.py and app/ expected); "
            "clone https://github.com/harry0703/MoneyPrinterTurbo there, or pass --mpt-home / set MPT_HOME"
        )
    chosen = python or os.environ.get("MPT_PYTHON")
    if chosen:
        if os.sep in chosen:
            # A path (not a bare command name) is relative to where the user is, and MPT is started from its own directory.
            command = str(Path(chosen).expanduser().resolve())
            runnable = Path(command).is_file() and os.access(command, os.X_OK)
        else:
            command, runnable = chosen, shutil.which(chosen) is not None
        if not runnable:
            raise MptError(f"cannot run {chosen!r} (from --mpt-python or $MPT_PYTHON): it is not an executable file, nor a command on PATH")
        return MptEnv(path, (command,))
    venv_python = path / ".venv" / "bin" / "python"
    if venv_python.is_file() and os.access(venv_python, os.X_OK):  # the same test as for a Python that was chosen
        return MptEnv(path, (str(venv_python),))
    if shutil.which("uv"):
        return MptEnv(path, ("uv", "run", "--frozen", "python"))
    raise MptError(f"no Python for MPT: {path}/.venv/bin/python is missing or cannot be run, and uv is not installed (run `uv sync --frozen` in {path})")


def video_params(job: Job) -> dict:
    """The VideoParams object MPT's --batch-file reads for this job. Unknown names are rejected there, so keep to its fields."""
    params: dict = {
        "video_subject": job.title,
        "video_script": job.script,
        "video_aspect": job.aspect,
        "video_language": job.language,
        "video_source": job.material_source,
        "video_clip_duration": job.clip_seconds,
        "video_count": 1,
        "bgm_type": "" if job.bgm == "none" else "random" if job.bgm == "random" else "custom",
        "bgm_volume": job.bgm_volume,
        "voice_rate": job.voice_rate,
        "voice_volume": job.voice_volume,
        "subtitle_enabled": job.subtitles,
        "font_name": job.font,
        "font_size": job.font_size,
        "n_threads": 2,
    }
    if params["bgm_type"] == "custom":
        params["bgm_file"] = job.bgm
    if job.audio_file:
        params["custom_audio_file"] = job.audio_file
    else:
        params["voice_name"] = job.voice if job.voice != NO_VOICE else NO_VOICE
    if job.material_source == "local":
        params["video_materials"] = [{"provider": "local", "url": url, "duration": 0} for url in job.materials]
    else:
        params["video_terms"] = list(job.terms)
    return params


def managed_file(env: MptEnv, name: str, folders: tuple[str, ...]) -> Path | None:
    """The file MPT will use for `name`: the first of `folders` (inside the MPT checkout) that holds it as a regular file whose real path
    stays inside that folder. MPT resolves real paths and refuses a file that leaves its folder (a link to somewhere else), and for music
    then tries its next folder (cli.py _resolve_managed_resource_file, app/services/bgm.py resolve_bgm_file)."""
    for folder in folders:
        base = os.path.realpath(env.home / folder)
        real = os.path.realpath(os.path.join(base, name))
        if os.path.isfile(real) and os.path.commonpath([base, real]) == base:
            return Path(real)
    return None


MIX_FAILED = "failed to mix background music"  # MPT logs this at ERROR level (app/services/video.py, generate_video) and renders on without the music


def music_mix_failure(log: str) -> str | None:
    """MPT's own account of a song it could not mix (a corrupt or undecodable file), from its stored log, or None. The video is still made
    and the narration keeps it audible, so nothing in the file shows the music is missing."""
    for line in log.splitlines():
        if MIX_FAILED in line:
            return line[line.index(MIX_FAILED):].strip()
    return None


def music_files(env: MptEnv) -> list[Path]:
    """The songs MPT picks from for `random` music, as app/services/bgm.py _list_bgm_files lists them: files with a supported suffix in
    storage/bgm or resource/songs, not its own upload staging files, whose real path stays in the folder; for a name in both folders the
    one in storage/bgm. With none, MPT logs a warning and renders without music, and the video still passes QA on its narration."""
    names: set[str] = set()
    for folder in MUSIC_FOLDERS:
        try:
            names.update(os.listdir(env.home / folder))
        except OSError:  # missing, or a folder that cannot be listed: it offers no song MPT could pick either
            pass
    found = []
    for name in sorted(names):
        if name.lower().startswith(".bgm-upload-") or Path(name).suffix.lower() not in MUSIC_EXTENSIONS:
            continue
        path = managed_file(env, name, MUSIC_FOLDERS)
        if path is not None:
            found.append(path)
    return found


def readable(path: Path) -> bool:
    try:
        open(path, "rb").close()
    except OSError:
        return False
    return True


def _digest_in(env: MptEnv, name: str, folders: tuple[str, ...]) -> str:
    path = managed_file(env, name, folders)
    if path is None:
        return FILE_MISSING
    try:
        with open(path, "rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return FILE_UNREADABLE


def input_digests(env: MptEnv, job: Job) -> dict[str, str]:
    """SHA-256 of the files the pack names that MPT reads from its own directories: the custom music (only when its volume is above zero;
    MPT looks in MUSIC_FOLDERS: storage/bgm, then resource/songs) and the subtitle font (only when subtitles are on; resource/fonts).

    A file that is needed and not there is FILE_MISSING, one that is there and cannot be read is FILE_UNREADABLE. These files are outside the pack, so the job's fingerprint cannot cover them:
    the digests are kept beside the fingerprint instead. What the pack does not name (MPT's config.toml, MPT itself) is not covered."""
    digests: dict[str, str] = {}
    if job.bgm not in ("none", "random") and job.bgm_volume > 0:
        digests["bgm"] = _digest_in(env, job.bgm, MUSIC_FOLDERS)
    if job.subtitles:
        digests["font"] = _digest_in(env, job.font, ("resource/fonts",))
    return digests


def _secrets(value, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _secrets(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in _secrets(v, key)]
    if isinstance(value, str) and value.strip() and SECRET_KEY.search(key):  # any length: the doc promises every key value is hidden
        return [value]
    return []


def config_of(env: MptEnv) -> dict:
    path = env.home / "config.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def redact(text: str, env: MptEnv) -> str:
    """Replace every secret value of MPT's config.toml in `text`. Logs and error messages go through here before they are stored."""
    for secret in sorted(_secrets(config_of(env)), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def _summary(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and isinstance(data.get("tasks"), list):
                return data
    return None


def _path(env: MptEnv, value) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (env.home / path).resolve()


def _stop(proc: subprocess.Popen) -> tuple[str, str]:
    """Kill MPT with everything it started (it leads its own process group) and collect what it had printed."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:  # it had just finished
        pass
    return proc.communicate()


def run_job(env: MptEnv, job: Job, workdir: Path, timeout: float) -> EngineResult:
    """Run MPT for one job and wait for it. Never raises for a failed render: the result says what failed."""
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = workdir.resolve() / "mpt-task.jsonl"  # MPT runs in its own directory, so a relative path would not be found there
    manifest.write_text(json.dumps(video_params(job), ensure_ascii=False) + "\n", encoding="utf-8")
    cmd = [*env.python, "cli.py", "--batch-file", str(manifest), "--stop-at", "video"]
    try:
        proc = subprocess.Popen(cmd, cwd=env.home, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:  # the interpreter went away after locate(), or cannot be executed
        return EngineResult(False, failed_stage="startup", error=f"cannot start {env.python[0]}: {exc.strerror or exc}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _, stderr = _stop(proc)
        return EngineResult(False, failed_stage="timeout", error=f"MPT did not finish within {timeout:g} s", log_tail=_log(env, workdir, stderr))
    except BaseException:
        # Ctrl-C, or SIGTERM (the CLI turns it into SystemExit), or anything else that ends the wait. MPT runs in its own session so it
        # gets no signal from the terminal: left alone it would go on rendering after this process lets go of the batch, and the next run
        # would start a second MPT beside it. Stop it and reap it, then let the interruption go on.
        _stop(proc)
        raise

    tail = _log(env, workdir, stderr)
    data = _summary(stdout)
    if not data or not data["tasks"]:
        reason = f"exit code {proc.returncode}, no task summary on stdout"
        if proc.returncode == 2:
            reason = f"MPT rejected the arguments or the manifest (exit code 2): {tail.strip().splitlines()[-1] if tail.strip() else ''}"
        return EngineResult(False, failed_stage="startup", error=reason, log_tail=tail)

    entry = data["tasks"][0]
    result = entry.get("result") or {}
    if entry.get("status") != "succeeded":
        return EngineResult(
            False, task_id=entry.get("task_id"), failed_stage=entry.get("failed_stage") or "unknown",
            error=redact(str(entry.get("error") or "unknown error"), env), log_tail=tail,
        )
    videos = result.get("videos") or []
    video = _path(env, videos[0]) if videos else None
    if not video or not video.is_file() or video.stat().st_size == 0:
        return EngineResult(False, task_id=entry.get("task_id"), failed_stage="video", error="MPT reported success but there is no video file", log_tail=tail)
    return EngineResult(
        True, task_id=entry.get("task_id"), video=video, audio=_path(env, result.get("audio_file")),
        subtitle=_path(env, result.get("subtitle_path")), task_dir=video.parent,
        audio_seconds=result.get("audio_duration"), warnings=tuple(result.get("warnings") or ()), log_tail=tail,
    )


def _log(env: MptEnv, workdir: Path, stderr: str) -> str:
    text = redact(stderr or "", env)
    (workdir / "mpt.log").write_text(text, encoding="utf-8")
    return "\n".join(text.strip().splitlines()[-12:])


def usable_keys(value) -> bool:
    """Whether a `*_api_keys` entry of config.toml gives MPT a key to send. MPT hands the entries out as they are (app/services/material.py
    get_api_key: a string whole, a list entry by rotation), so it needs at least one entry and every entry a non-blank string: a blank one
    would be sent as the key, and in a mixed list some requests would fail."""
    entries = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return bool(entries) and all(isinstance(entry, str) and entry.strip() for entry in entries)


def doctor_info(env: MptEnv) -> dict:
    """What the MPT config says, as yes/no and provider names. A key's value is never part of the answer."""
    app = config_of(env).get("app", {})
    return {
        "config.toml": (env.home / "config.toml").is_file(),
        "pexels_api_keys": usable_keys(app.get("pexels_api_keys")),
        "pixabay_api_keys": usable_keys(app.get("pixabay_api_keys")),
        "coverr_api_keys": usable_keys(app.get("coverr_api_keys")),
        "subtitle_provider": str(app.get("subtitle_provider", "edge")).strip().lower(),  # MPT reads it with .strip().lower()
        "llm_provider": app.get("llm_provider", ""),
    }
