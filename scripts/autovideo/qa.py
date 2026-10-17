"""Checks on a rendered video, made on the file and not on what the log says (ffprobe, ffmpeg volumedetect, the subtitle file).

An `error` check that fails means the video must not be published as it is; a `warn` check is for a person to look at.
Thresholds are conservative on purpose: they catch a silent, cut-off, wrong-shaped or wrongly subtitled video, not a dull one.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .pack import Job
from .transcript import Cue, coverage

RATIO = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0}
SILENT_DB = -50.0  # mean level below this is silence for our purpose (digital silence reads -91 dB)
MIN_COVERAGE = 0.8
LENGTH_GAP = 3.0  # seconds the video may run past (or stop short of) its narration


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    level: str = "error"

    def to_dict(self) -> dict:
        return asdict(self)


def passed(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.level == "error")


def probe(path: Path) -> dict | None:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def levels(path: Path) -> tuple[float | None, float | None]:
    """(mean dB, peak dB) of the audio of a file, or (None, None) when it has no readable audio."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    try:
        err = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stderr
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", err)
    peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", err)
    num = lambda m: None if not m else float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    return num(mean), num(peak)


def _duration(info: dict | None) -> float | None:
    try:
        return float(info["format"]["duration"])
    except (TypeError, KeyError, ValueError):
        return None


def check_video(job: Job, video: Path, narration: Path | None, cues: list[Cue]) -> list[Check]:
    checks: list[Check] = []
    add = lambda name, ok, detail, level="error": checks.append(Check(name, bool(ok), detail, level))

    info = probe(video) if video.is_file() and video.stat().st_size > 0 else None
    if not info:
        add("readable", False, f"ffprobe cannot read {video.name}")
        return checks
    add("readable", True, f"{video.name}, {video.stat().st_size / 1e6:.1f} MB")

    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    add("video_stream", len(vstreams) == 1, f"{len(vstreams)} video stream(s)")
    expects_audio = job.reads_aloud or job.audio_file is not None or job.bgm != "none"
    add("audio_stream", bool(astreams) or not expects_audio, f"{len(astreams)} audio stream(s)")

    if vstreams:
        w, h = int(vstreams[0].get("width", 0)), int(vstreams[0].get("height", 0))
        want = RATIO[job.aspect]
        add("aspect", h > 0 and abs(w / h - want) / want < 0.02, f"{w}x{h}, wanted {job.aspect}")

    seconds = _duration(info)
    if seconds is None:
        add("duration", False, "no duration in the file")
    else:
        add("duration", job.min_seconds <= seconds <= job.max_seconds, f"{seconds:.1f} s, target {job.min_seconds:g} to {job.max_seconds:g} s")

    if astreams and expects_audio:
        mean, peak = levels(video)
        add("audible", mean is not None and mean > SILENT_DB, f"mean {mean} dB, peak {peak} dB; silence is below {SILENT_DB:g} dB")
    if narration and narration.is_file() and (job.reads_aloud or job.audio_file):
        mean, _ = levels(narration)
        add("narration_audible", mean is not None and mean > SILENT_DB, f"{narration.name}: mean {mean} dB")
        spoken = _duration(probe(narration))
        if spoken and seconds:
            add("length_matches_narration", abs(seconds - spoken) <= LENGTH_GAP, f"video {seconds:.1f} s, narration {spoken:.1f} s", "warn")

    if job.subtitles and (job.reads_aloud or job.audio_file):
        add("subtitles_made", bool(cues), f"{len(cues)} cue(s)")
    if cues:
        ordered = all(c.end > c.start for c in cues) and all(b.start >= a.start for a, b in zip(cues, cues[1:]))
        add("subtitle_order", ordered, "every cue ends after it starts, in order")
        if seconds:
            add("subtitle_inside_video", cues[-1].end <= seconds + 0.5, f"last cue ends at {cues[-1].end:.1f} s, video {seconds:.1f} s")
        share = coverage(job.script, cues)
        add("subtitle_text", share >= MIN_COVERAGE, f"{share:.0%} of the script's words are in the subtitles (needs {MIN_COVERAGE:.0%})")
    return checks
