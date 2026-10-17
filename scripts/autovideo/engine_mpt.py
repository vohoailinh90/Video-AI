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

from .pack import NO_VOICE, Job

DEFAULT_HOME = Path("~/MoneyPrinterTurbo")
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
    if venv_python.is_file():
        return MptEnv(path, (str(venv_python),))
    if shutil.which("uv"):
        return MptEnv(path, ("uv", "run", "--frozen", "python"))
    raise MptError(f"no Python for MPT: {path}/.venv is missing and uv is not installed (run `uv sync --frozen` in {path})")


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


def bgm_digest(env: MptEnv, job: Job) -> str | None:
    """SHA-256 of the custom music file the job names, found where MPT looks for it (storage/bgm, then resource/songs).

    None when the job reads no custom music (none, random, or a volume of zero) or the file is not there. The file lives in MPT's own
    directories, outside the pack, so the job's fingerprint cannot cover it: the digest is kept beside the fingerprint instead."""
    if job.bgm in ("none", "random") or job.bgm_volume <= 0:
        return None
    for folder in ("storage/bgm", "resource/songs"):
        path = env.home / folder / job.bgm
        if path.is_file():
            with open(path, "rb") as handle:
                return hashlib.file_digest(handle, "sha256").hexdigest()
    return None


def _secrets(value, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _secrets(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in _secrets(v, key)]
    if isinstance(value, str) and len(value) >= 8 and SECRET_KEY.search(key):
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
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        return EngineResult(False, failed_stage="timeout", error=f"MPT did not finish within {timeout:g} s", log_tail=_log(env, workdir, stderr))

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


def doctor_info(env: MptEnv) -> dict:
    """What the MPT config says, as yes/no and provider names. A key's value is never part of the answer."""
    app = config_of(env).get("app", {})
    return {
        "config.toml": (env.home / "config.toml").is_file(),
        "pexels_api_keys": bool(app.get("pexels_api_keys")),
        "pixabay_api_keys": bool(app.get("pixabay_api_keys")),
        "coverr_api_keys": bool(app.get("coverr_api_keys")),
        "subtitle_provider": app.get("subtitle_provider", "edge"),
        "llm_provider": app.get("llm_provider", ""),
    }
