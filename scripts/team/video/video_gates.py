#!/usr/bin/env python3
"""Verdict on a rendered video: does it have sound, and does it match what was asked?

The video team's gates run this on the draft render (docs/vps-team-video.md). Every
check has a computable answer, so none of it is left to a model (CLAUDE.md,
"Deterministic work is not agent work"): a model listening to a file can be
wrong; ffprobe and ffmpeg's loudness meter cannot.

    video_gates.py renders/draft.mp4 --expect videos/V01.expected.json

`expected.json` is written by the tester stage from the spec. Keys (all optional
except `duration_s`; an unknown key is an error, so a typo cannot disable a check):

    duration_s, duration_tolerance_s (1.5)   video length, of the container and of the picture stream alone
    width, height, fps                       exact size; fps within 0.05
    audio.required (true)                    an audio stream must exist
    audio.min_coverage (0.9)                 audio length / video length
    audio.lufs_min (-30), audio.lufs_max (-10)   integrated loudness window
    audio.max_peak_db (-0.1)                 true peak: above it the mix clips
    audio.max_silence_gap_s (4.0)            longest silence, the missing tail of a short audio stream included

Prints one PASS/FAIL line per check and, last, one JSON summary line (the gates
log keeps only the tail). Exit 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

NUMBER_KEYS = {"duration_s", "duration_tolerance_s", "width", "height", "fps"}
TOP_KEYS = NUMBER_KEYS | {"audio"}
AUDIO_NUMBER_KEYS = {"min_coverage", "lufs_min", "lufs_max", "max_peak_db", "max_silence_gap_s"}
AUDIO_KEYS = AUDIO_NUMBER_KEYS | {"required"}
SILENCE_FLOOR_DB = -45  # below this a stretch counts as silence
SILENCE_MIN_S = 0.2  # silencedetect reports stretches at least this long: short enough to see a trailing one that is
EOF_EDGE_S = 0.25  # only completed by the missing tail of the audio. A silence ending this close to the stream's end reaches it
LUFS_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+|-inf)\s*LUFS")
PEAK_RE = re.compile(r"True peak:\s*\n\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS")
SIL_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
SIL_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def load_expected(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{path}: cannot read expected.json ({exc})")
    if not isinstance(data, dict) or not is_number(data.get("duration_s")):
        raise SystemExit(f"{path}: expected a JSON object whose duration_s must be a number")
    audio = data.get("audio", {})
    if not isinstance(audio, dict):
        raise SystemExit(f"{path}: audio must be an object")
    unknown = (set(data) - TOP_KEYS) | {f"audio.{k}" for k in set(audio) - AUDIO_KEYS}
    if unknown:
        raise SystemExit(f"{path}: unknown key(s) {', '.join(sorted(unknown))}")
    # A string where a number belongs would crash a comparison later, and `true` would pass as 1.
    wrong = [k for k in NUMBER_KEYS & set(data) if not is_number(data[k])]
    wrong += [f"audio.{k}" for k in AUDIO_NUMBER_KEYS & set(audio) if not is_number(audio[k])]
    if "required" in audio and not isinstance(audio["required"], bool):
        wrong.append("audio.required")
    if wrong:
        raise SystemExit(f"{path}: {', '.join(sorted(wrong))} must be {'a number' if 'audio.required' not in wrong else 'a number or true/false'}")
    return data


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def number(text: str) -> float:
    return float("-inf") if text == "-inf" else float(text)


def parse_loudness(stderr: str) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBFS) from ffmpeg's ebur128 summary."""
    lufs, peak = LUFS_RE.search(stderr), PEAK_RE.search(stderr)
    return (number(lufs[1]) if lufs else None, number(peak[1]) if peak else None)


def parse_silences(stderr: str, audio_length: float) -> tuple[list[float], float]:
    """(lengths of the silent stretches inside the audio, length of the one that reaches the end of the stream).

    The one at the end is kept apart because the stretch of the video after the audio stream ends is silent too, and
    the two are a single silence. Depending on the ffmpeg version, silencedetect either never closes it or closes it at
    the stream's last frame; both read as reaching `audio_length`."""
    gaps: list[float] = []
    trailing = 0.0
    start: float | None = None
    for row in stderr.splitlines():
        found_start, found_end = SIL_START_RE.search(row), SIL_END_RE.search(row)
        if found_start:
            start = max(0.0, float(found_start[1]))
        elif found_end and start is not None:
            end = float(found_end[1])
            if end >= audio_length - EOF_EDGE_S:
                trailing = audio_length - start
            else:
                gaps.append(end - start)
            start = None
    if start is not None:
        trailing = audio_length - start
    return gaps, trailing


def probe(video: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"ffprobe could not read {video}: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def frame_rate(stream: dict) -> float:
    """avg_frame_rate is "30000/1001", "25", or "N/A"/"0/0" when ffprobe cannot tell: that reads as 0."""
    top, _, bottom = str(stream.get("avg_frame_rate", "0/1")).partition("/")
    try:
        return float(top) / float(bottom or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def audio_levels(video: Path, gap: float) -> tuple[str, str]:
    """Run the loudness meter and the silence detector over the audio once each."""
    def run(filters: str) -> str:
        return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(video), "-vn", "-af", filters,
                               "-f", "null", "-"], capture_output=True, text=True).stderr
    return run("ebur128=peak=true"), run(f"silencedetect=noise={SILENCE_FLOOR_DB}dB:d={gap}")


def evaluate(info: dict, loudness: tuple[float | None, float | None] | None, gaps: list[float],
             expected: dict, trailing: float = 0.0) -> list[tuple[bool, str, str]]:
    """(ok, check name, detail) per check. Pure: the media was read by the caller."""
    checks: list[tuple[bool, str, str]] = []

    def check(ok: bool, name: str, detail: str) -> None:
        checks.append((bool(ok), name, detail))

    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    opts = expected.get("audio", {})
    length = float(info.get("format", {}).get("duration") or 0)
    tolerance = float(expected.get("duration_tolerance_s", 1.5))
    check(video, "video stream", "present" if video else "missing")
    check(abs(length - expected["duration_s"]) <= tolerance, "duration",
          f"{length:.2f}s, wanted {expected['duration_s']}s +/- {tolerance}s")
    if video:
        # The container is as long as its longest stream: 6 s of sound under a picture that stopped at 2 s still reads 6 s.
        picture = video.get("duration")
        picture_length = float(picture) if picture not in (None, "N/A") else None
        check(picture_length is not None and abs(picture_length - expected["duration_s"]) <= tolerance, "video duration",
              f"{'unmeasured' if picture_length is None else f'{picture_length:.2f}s'}, wanted {expected['duration_s']}s +/- {tolerance}s")
        for key in ("width", "height"):
            if key in expected:
                check(video.get(key) == expected[key], key, f"{video.get(key)}, wanted {expected[key]}")
        if "fps" in expected:
            fps = frame_rate(video)
            check(abs(fps - expected["fps"]) <= 0.05, "fps", f"{fps:.2f}, wanted {expected['fps']}")
    if not opts.get("required", True):
        return checks
    check(audio, "audio stream", "present" if audio else "missing: the render is silent")
    if not audio:
        return checks
    audio_length = float(audio.get("duration") or length)
    coverage = audio_length / length if length else 0.0
    check(coverage >= opts.get("min_coverage", 0.9), "audio coverage",
          f"audio is {coverage:.0%} of the video, wanted at least {opts.get('min_coverage', 0.9):.0%}")
    lufs, peak = loudness or (None, None)
    low, high = opts.get("lufs_min", -30), opts.get("lufs_max", -10)
    check(lufs is not None and low <= lufs <= high, "loudness",
          f"{'unmeasured' if lufs is None else f'{lufs:.1f} LUFS'}, wanted {low}..{high} LUFS")
    ceiling = opts.get("max_peak_db", -0.1)
    check(peak is not None and peak <= ceiling, "true peak",
          f"{'unmeasured' if peak is None else f'{peak:.1f} dBFS'}, ceiling {ceiling} dBFS")
    # silencedetect only sees the audio stream: whatever follows its end, up to the end of the video, is silence too, and
    # it continues a silence that was already running when the stream ended.
    tail = max(0.0, length - audio_length)
    longest = max(max(gaps, default=0.0), trailing + tail)
    limit = opts.get("max_silence_gap_s", 4.0)
    check(longest <= limit, "silence gap", f"longest silence {longest:.1f}s, limit {limit}s")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video", type=Path)
    parser.add_argument("--expect", type=Path, required=True, help="expected.json")
    args = parser.parse_args(argv)
    expected = load_expected(args.expect)
    for tool in ("ffprobe", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is not installed")
    if not args.video.is_file() or args.video.stat().st_size == 0:
        print(f"FAIL render: {args.video} is missing or empty")
        print(json.dumps({"ok": False, "failed": ["render"]}))
        return 1
    info = probe(args.video)
    opts = expected.get("audio", {})
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    loudness, gaps, trailing = None, [], 0.0
    if has_audio and opts.get("required", True):
        container = float(info.get("format", {}).get("duration") or 0)
        stream = next(s for s in info["streams"] if s.get("codec_type") == "audio")
        meter, silence = audio_levels(args.video, SILENCE_MIN_S)
        loudness = parse_loudness(meter)
        gaps, trailing = parse_silences(silence, float(stream.get("duration") or container))
    checks = evaluate(info, loudness, gaps, expected, trailing)
    for ok, name, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    failed = [name for ok, name, _ in checks if not ok]
    print(json.dumps({"ok": not failed, "failed": failed, "checks": len(checks)}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
