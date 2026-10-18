"""Render a video project again with another set of narration clips, without touching the project.

It copies the project to a temporary directory, puts the clips in assets/ as <id>.wav, rewrites the data-start, data-duration
and data-volume of the matching <audio id="<id>"> tags in index.html, runs `npm run check`, renders, and reports the result.

  * data-start comes from voiceover.json, data-duration from the clip length (+0.01 s).
  * data-volume brings each clip's mean level to --target-mean dB, but never lets the peak go above --max-peak dB.
  * A clip that would run into the scene's fade-out is reported as a warning.
  * With --apply, once the check and the render have passed, the same clips and the rewritten index.html are also written into
    the project itself. That is how a voice becomes the project's default: assets/<id>.wav and the <audio> tags then match it.

usage:
  python -I scripts/vo/revoice.py --project videos/demo-video --lines videos/demo-video/voiceover.json \\
      --clips videos/demo-video/voices/mai-anh --out videos/demo-video/renders/demo-video-mai-anh.mp4
  python -I scripts/vo/revoice.py ... --clips build/voices/hai-dang --out videos/demo-video/renders/demo-video.mp4 --apply

Needs node/npm, ffmpeg and ffprobe, and a Chrome headless shell for the render (npx hyperframes browser ensure).
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # line_ids.py next to this file; -I does not add the script's folder
from line_ids import require_file_name_ids  # noqa: E402

FADE_OUT = 0.35  # seconds; the fade-out of every scene in index.html


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], check=True).stdout
    return float(out.strip())


def levels(path: Path):
    """(mean dB, peak dB) of a file, from ffmpeg's volumedetect."""
    err = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"]).stderr
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", err)
    return float(mean.group(1)), float(peak.group(1))


def set_attr(tag: str, name: str, value: str) -> str:
    pattern = re.compile(rf'{name}="[^"]*"')
    assert pattern.search(tag), f"{name} missing in {tag}"
    return pattern.sub(f'{name}="{value}"', tag, count=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="HyperFrames project directory (has index.html and package.json)")
    ap.add_argument("--lines", required=True, help="voiceover.json")
    ap.add_argument("--clips", required=True, help="directory with <id>.wav for every line")
    ap.add_argument("--out", required=True, help="mp4 to write")
    ap.add_argument("--target-mean", type=float, default=-19.0, help="mean level of each clip in dB (default: %(default)s)")
    ap.add_argument("--max-peak", type=float, default=-1.5, help="highest allowed peak of a clip in dB (default: %(default)s)")
    ap.add_argument("--apply", action="store_true", help="after a successful render, write the clips and index.html into --project (make this voice the default)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary project copy and print its path")
    ap.add_argument("--skip-check", action="store_true", help="do not run npm run check before rendering")
    args = ap.parse_args()

    project, clips, out = Path(args.project), Path(args.clips), Path(args.out).resolve()
    lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))["lines"]
    require_file_name_ids(lines)
    work = Path(tempfile.mkdtemp(prefix="revoice-")) / project.name
    shutil.copytree(project, work, ignore=shutil.ignore_patterns("renders", ".hyperframes", "node_modules", "voices"))
    html_path = work / "index.html"
    html = html_path.read_text(encoding="utf-8")

    print(f"{'clip':6s} {'start':>6s} {'length':>7s} {'mean':>7s} {'peak':>7s} {'volume':>7s}")
    for line in lines:
        clip = clips / f"{line['id']}.wav"
        if not clip.is_file():
            print(f"missing clip: {clip}", file=sys.stderr)
            return 1
        shutil.copyfile(clip, work / "assets" / f"{line['id']}.wav")
        length = duration(clip)
        mean, peak = levels(clip)
        gain_db = min(args.target_mean - mean, args.max_peak - peak)
        volume = 1.0 if abs(gain_db) < 0.5 else round(10 ** (gain_db / 20), 2)
        tag_re = re.compile(rf'<audio id="{re.escape(line["id"])}"[^>]*>')
        found = tag_re.search(html)
        if not found:
            print(f'no <audio id="{line["id"]}"> in index.html', file=sys.stderr)
            return 1
        tag = found.group(0)
        tag = set_attr(tag, "data-start", f"{line['start']:g}")
        tag = set_attr(tag, "data-duration", f"{math.ceil(length * 100) / 100 + 0.01:.2f}")
        tag = set_attr(tag, "data-volume", f"{volume:g}")
        html = html[:found.start()] + tag + html[found.end():]
        print(f"{line['id']:6s} {line['start']:6.2f} {length:6.2f}s {mean:6.1f}  {peak:6.1f}  {volume:7g}")
        if line["start"] + length > line["scene_end"] - FADE_OUT:
            print(f"  WARNING: {line['id']} ends at {line['start'] + length:.2f} s, inside the {FADE_OUT} s fade-out "
                  f"of its scene (scene ends at {line['scene_end']} s)")
    html_path.write_text(html, encoding="utf-8")

    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1"}
    if not args.skip_check:
        check = run(["npm", "run", "check"], cwd=work, env=env)
        text = re.sub(r"\x1b\[[0-9;]*m", "", check.stdout + check.stderr)
        verdict = [l.strip() for l in text.splitlines() if re.search(r"error\(s\)|Check (passed|failed)", l)]
        print("check:", " | ".join(verdict) or "(no summary)")
        if check.returncode != 0 or "Check failed" in text:
            print(text[-3000:], file=sys.stderr)
            return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    render = run(["npm", "run", "render", "--", "--output", str(out)], cwd=work, env=env)
    if render.returncode != 0 or not out.is_file():
        print(re.sub(r"\x1b\[[0-9;]*m", "", render.stdout + render.stderr)[-3000:], file=sys.stderr)
        return 1

    if args.apply:
        for line in lines:
            shutil.copyfile(work / "assets" / f"{line['id']}.wav", project / "assets" / f"{line['id']}.wav")
        (project / "index.html").write_text(html, encoding="utf-8")
        print(f"applied: {len(lines)} clips and index.html written into {project}")

    probe = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,duration",
                 "-of", "compact", str(out)], check=True).stdout.strip()
    mean, peak = levels(out)
    print(f"rendered: {out}\n{probe}\nwhole file: mean {mean} dB, peak {peak} dB")
    if args.keep:
        print("project copy kept at:", work)
    else:
        shutil.rmtree(work.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
