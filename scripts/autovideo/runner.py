"""Render the jobs of a pack one after another, keep what each one made in its own folder, and remember how far it got.

    <out>/<batch>/state.json            status and fingerprint of every job: a rerun skips what is done and unchanged
    <out>/<batch>/summary.json, .md     the last run in one table
    <out>/<batch>/<id>/video.mp4        the video
                       narration.mp3    the voice (or the audio_file the job was given)
                       subtitles.srt    cues as MPT wrote them
                       transcript.txt   the words, one scene per paragraph
                       transcript.json  scenes and cues with their times
                       job.json         the job as rendered, with its fingerprint
                       report.json      engine result, QA checks, timing
                       mpt.log          the tail MPT printed, with MPT's secrets removed

MPT is run one job at a time (its own guidance: never two renders at once).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import engine_mpt, qa
from .pack import Job, Pack
from .transcript import parse_srt, transcript

OUTPUT_FILES = ("video.mp4", "subtitles.srt", "transcript.txt", "transcript.json", "job.json", "report.json", "mpt.log", "mpt-task.jsonl")
NO_RETRY = {"preflight", "startup", "timeout"}  # a second try cannot help: the setup is wrong, or it already took too long
STATES = ("done", "qa_failed", "failed", "running")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state(batch_dir: Path) -> dict:
    try:
        return json.loads((batch_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": {}}


def write_json(path: Path, data) -> None:
    """Write through a temporary file, so an interrupted run never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def preflight(env: engine_mpt.MptEnv, job: Job) -> str | None:
    """Reasons a render cannot work, found before MPT starts. None when nothing is wrong."""
    info = engine_mpt.doctor_info(env)
    key = f"{job.material_source}_api_keys"
    if job.material_source != "local" and not info.get(key):
        return f"{key} is empty in {env.home}/config.toml (get a free key from the {job.material_source} website)"
    if not (env.home / "resource" / "fonts" / job.font).is_file():
        return f"font {job.font} is not in {env.home}/resource/fonts"
    if job.bgm not in ("none", "random") and not any((env.home / d / job.bgm).is_file() for d in ("storage/bgm", "resource/songs")):
        return f"music file {job.bgm} is in neither storage/bgm nor resource/songs of {env.home}"
    if job.audio_file and job.subtitles and info["subtitle_provider"] != "whisper":
        return "audio_file with subtitles needs subtitle_provider = \"whisper\" in config.toml; set subtitles to false or change it"
    return None


def collect(job: Job, result: engine_mpt.EngineResult, dest: Path) -> dict:
    """Copy what MPT made into the job's folder and write the transcript. Returns the file names."""
    for name in OUTPUT_FILES[:5]:
        (dest / name).unlink(missing_ok=True)
    for old in dest.glob("narration.*"):
        old.unlink()
    files: dict = {"video": "video.mp4", "narration": None, "subtitles": None}
    shutil.copyfile(result.video, dest / "video.mp4")
    if result.audio and result.audio.is_file():
        files["narration"] = f"narration{result.audio.suffix.lower()}"
        shutil.copyfile(result.audio, dest / files["narration"])
    cues = []
    if result.subtitle and result.subtitle.is_file():
        files["subtitles"] = "subtitles.srt"
        shutil.copyfile(result.subtitle, dest / "subtitles.srt")
        cues = parse_srt(result.subtitle.read_text(encoding="utf-8", errors="replace"))
    plain, document = transcript(job, cues, files["narration"], files["subtitles"])
    (dest / "transcript.txt").write_text(plain, encoding="utf-8")
    write_json(dest / "transcript.json", document)
    write_json(dest / "job.json", {**job.to_dict(), "fingerprint": job.fingerprint()})
    return files


def evaluate(job: Job, dest: Path) -> list[qa.Check]:
    """QA on the files in a job's folder."""
    srt = dest / "subtitles.srt"
    cues = parse_srt(srt.read_text(encoding="utf-8", errors="replace")) if srt.is_file() else []
    narration = next(iter(sorted(dest.glob("narration.*"))), None)
    return qa.check_video(job, dest / "video.mp4", narration, cues)


def rendered_fingerprint(dest: Path) -> str | None:
    """Fingerprint of the job as it was rendered into `dest`. job.json is written together with the video, so it says whose video it is."""
    try:
        return json.loads((dest / "job.json").read_text(encoding="utf-8")).get("fingerprint")
    except (OSError, ValueError, AttributeError):
        return None


def qa_basis(job: Job) -> list[float]:
    """What QA measured the video against and the fingerprint leaves out (a QA limit does not change the render)."""
    return [job.min_seconds, job.max_seconds]


def job_status(entry: dict | None, job: Job, dest: Path) -> str:
    """What a job amounts to now: pending, stale, missing, unchecked, or the status its last run recorded (done, qa_failed, failed, running).

    `done` is only said when the state, the files and the QA limits agree: the state alone is not enough, because a failed render of an
    edited job leaves the old video in the folder, a video can be deleted, and narrowing target_seconds changes what passes."""
    if not entry:
        return "pending"
    if entry.get("fingerprint") != job.fingerprint():
        return "stale"  # the pack changed after it was rendered
    status = entry.get("status", "pending")
    if status != "done":
        return status
    if not (dest / "video.mp4").is_file():
        return "missing"
    if rendered_fingerprint(dest) != job.fingerprint():
        return "stale"
    if entry.get("qa_basis") != qa_basis(job):
        return "unchecked"  # done under other QA limits
    return "done"


def run(
    pack: Pack,
    env: engine_mpt.MptEnv,
    out_root: Path,
    *,
    only: list[str] | None = None,
    force: bool = False,
    retries: int = 1,
    timeout: float = 1800,
    log: Callable[[str], None] = print,
) -> dict:
    if retries < 0 or not (math.isfinite(timeout) and timeout > 0):
        raise ValueError("retries must be 0 or more, and timeout a positive number of seconds")
    batch_dir = out_root / pack.batch
    ids = [job.id for job in pack.jobs]
    unknown = [i for i in (only or []) if i not in ids]
    if unknown:
        raise ValueError(f"no such video in the pack: {', '.join(unknown)} (the pack has {', '.join(ids)})")
    selected = [job for job in pack.jobs if not only or job.id in only]
    state = read_state(batch_dir)
    state["batch"] = pack.batch
    rows = []

    for number, job in enumerate(selected, start=1):
        dest = batch_dir / job.id
        entry = state["jobs"].get(job.id)
        label = f"[{number}/{len(selected)}] {job.id}"
        status = "pending" if force else job_status(entry, job, dest)
        if status == "unchecked":
            # Only the QA limits changed since the last check: look at the video that is there again, do not render it again.
            status = requalify_job(job, dest, state)["status"]
            write_json(batch_dir / "state.json", state)
            log(f"{label}: QA limits changed, checked again: {status}")
        if status == "done":
            log(f"{label}: done already, skipped")
            rows.append({"id": job.id, "status": "skipped", "seconds": entry.get("seconds"), "qa_failures": []})
            continue

        attempts = (entry or {}).get("attempts", 0) if not force else 0
        started = time.monotonic()
        state["jobs"][job.id] = {"status": "running", "fingerprint": job.fingerprint(), "attempts": attempts, "started": now()}
        write_json(batch_dir / "state.json", state)
        dest.mkdir(parents=True, exist_ok=True)

        problem = preflight(env, job)
        outcome: dict
        if problem:
            outcome = {"status": "failed", "stage": "preflight", "error": problem}
            log(f"{label}: cannot start: {problem}")
        else:
            outcome = {}
            for attempt in range(1, retries + 2):
                attempts += 1
                log(f"{label}: rendering ({job.title}), attempt {attempt}")
                result = engine_mpt.run_job(env, job, dest, timeout)
                if not result.ok:
                    outcome = {"status": "failed", "stage": result.failed_stage, "error": result.error, "log_tail": result.log_tail}
                    log(f"{label}: failed at {result.failed_stage}: {result.error}")
                    if result.failed_stage in NO_RETRY:
                        break
                    continue
                files = collect(job, result, dest)
                checks = evaluate(job, dest)
                bad = [c for c in checks if c.level == "error" and not c.ok]
                outcome = {
                    "status": "done" if not bad else "qa_failed", "files": files, "checks": [c.to_dict() for c in checks],
                    "engine": {
                        "name": "moneyprinterturbo", "task_id": result.task_id, "task_dir": str(result.task_dir),
                        "audio_seconds": result.audio_seconds, "warnings": list(result.warnings),
                    },
                }
                if not bad:
                    break
                log(f"{label}: rendered, QA failed: " + "; ".join(f"{c.name} ({c.detail})" for c in bad))

        seconds = round(time.monotonic() - started, 1)
        report = {"id": job.id, "attempts": attempts, "seconds": seconds, "finished": now(), "fingerprint": job.fingerprint(), **outcome}
        write_json(dest / "report.json", report)
        state["jobs"][job.id] = {
            "status": outcome["status"], "fingerprint": job.fingerprint(), "attempts": attempts, "seconds": seconds, "finished": report["finished"],
            "task_id": outcome.get("engine", {}).get("task_id"), "stage": outcome.get("stage"), "error": outcome.get("error"),
            "qa_basis": qa_basis(job) if "checks" in outcome else None,
        }
        write_json(batch_dir / "state.json", state)
        failures = [c["name"] for c in outcome.get("checks", []) if c["level"] == "error" and not c["ok"]]
        rows.append({"id": job.id, "status": outcome["status"], "seconds": seconds, "stage": outcome.get("stage"), "error": outcome.get("error"), "qa_failures": failures})
        if outcome["status"] == "done":
            log(f"{label}: done in {seconds:g} s -> {dest / 'video.mp4'}")

    summary = summarise(pack, rows, batch_dir)
    return summary


def summarise(pack: Pack, rows: list[dict], batch_dir: Path) -> dict:
    count = lambda status: sum(1 for r in rows if r["status"] == status)
    summary = {
        "batch": pack.batch, "output": str(batch_dir), "finished": now(), "total": len(rows), "done": count("done"), "skipped": count("skipped"),
        "failed": count("failed"), "qa_failed": count("qa_failed"), "videos": rows,
    }
    write_json(batch_dir / "summary.json", summary)
    lines = [f"# {pack.batch}", "", "| video | status | seconds | note |", "|---|---|---|---|"]
    for r in rows:
        note = r.get("error") or ", ".join(r["qa_failures"]) or ""
        lines.append(f"| {r['id']} | {r['status']} | {r.get('seconds') if r.get('seconds') is not None else ''} | {note.replace('|', '/')} |")
    (batch_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def requalify(pack: Pack, out_root: Path, only: list[str] | None = None) -> list[dict]:
    """Run QA again on the folders that hold this version of each job, without rendering. Use after changing target_seconds or the QA code."""
    batch_dir = out_root / pack.batch
    unknown = [i for i in (only or []) if i not in [job.id for job in pack.jobs]]
    if unknown:
        raise ValueError(f"no such video in the pack: {', '.join(unknown)}")
    state = read_state(batch_dir)
    rows = []
    for job in pack.jobs:
        if only and job.id not in only:
            continue
        rows.append(requalify_job(job, batch_dir / job.id, state))
    write_json(batch_dir / "state.json", state)
    return rows


def requalify_job(job: Job, dest: Path, state: dict) -> dict:
    """QA on one folder, and the state updated to match. A folder that does not hold this version of the job is not checked."""
    if not (dest / "video.mp4").is_file():
        return {"id": job.id, "status": "missing", "checks": []}
    if rendered_fingerprint(dest) != job.fingerprint():
        # The folder holds a video of an earlier version of this job (its newer render failed or never finished).
        # Passing QA does not make it the video of this job, so it is neither checked nor marked done.
        return {"id": job.id, "status": "stale", "checks": []}
    checks = evaluate(job, dest)
    entry = state["jobs"].setdefault(job.id, {})
    entry.update(fingerprint=job.fingerprint(), status="done" if qa.passed(checks) else "qa_failed", qa_basis=qa_basis(job))
    try:
        report = json.loads((dest / "report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {"id": job.id}
    report.update({"status": entry["status"], "checks": [c.to_dict() for c in checks], "requalified": now()})
    write_json(dest / "report.json", report)
    return {"id": job.id, "status": entry["status"], "checks": [c.to_dict() for c in checks]}
