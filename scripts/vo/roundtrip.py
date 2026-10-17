"""Round-trip check: let PhoWhisper listen to synthesized speech and compare what it heard with the text that was read.

Two inputs:
  * one or more manifest.json files written by synth.py (checks the raw clips), or
  * --video a rendered mp4 plus --lines voiceover.json (cuts one window per line out of the video's audio, so the music bed
    and the mix are part of the test).

WER = word edit distance / words in the reference, after lowercasing and removing punctuation. It is a rough proxy: a loanword
such as "video" or "MP4" can be written several valid ways, and PhoWhisper writes lowercase text without punctuation.
It says whether the speech is understandable, not whether it sounds natural.

usage:
  python -I scripts/vo/roundtrip.py --out results.json build/voices/mai-anh/manifest.json
  python -I scripts/vo/roundtrip.py --out results.json --video renders/demo.mp4 --lines videos/demo-video/voiceover.json --label "final mix"

Needs the packages in scripts/vo/requirements-asr.txt and ffmpeg. The first run downloads vinai/PhoWhisper-small (about 1 GB).
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path


def words(text: str) -> list:
    return re.sub(r"[^\w\s]", "", text.lower()).split()


def edit_distance(a: list, b: list) -> int:
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1]


def items_from_video(video: Path, lines_path: Path, label: str, work: Path) -> list:
    lines = json.loads(lines_path.read_text(encoding="utf-8"))["lines"]
    work.mkdir(parents=True, exist_ok=True)
    items = []
    for line in lines:
        start = max(0.0, line["start"] - 0.2)
        length = max(1.0, line["scene_end"] - 0.3 - start)
        wav = work / f"{line['id']}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            check=True,
        )
        items.append({"engine": label, "voice": "mix", "id": line["id"], "group": "narration",
                      "text": line["text"], "path": str(wav)})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifests", nargs="*", help="manifest.json files from synth.py")
    ap.add_argument("--model", default="vinai/PhoWhisper-small", help="speech recognition model (default: %(default)s)")
    ap.add_argument("--out", required=True, help="where to write the results json")
    ap.add_argument("--video", help="rendered mp4 to cut the narration windows from")
    ap.add_argument("--lines", help="voiceover.json (required with --video)")
    ap.add_argument("--label", default="video", help="name shown for --video items")
    ap.add_argument("--work", help="directory for the cut windows (default: a temporary directory)")
    args = ap.parse_args()

    items = []
    for m in args.manifests:
        items += json.loads(Path(m).read_text(encoding="utf-8"))
    if args.video:
        if not args.lines:
            ap.error("--video needs --lines")
        work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="roundtrip-"))
        items += items_from_video(Path(args.video), Path(args.lines), args.label, work)
    if not items:
        ap.error("give at least one manifest.json or --video")

    from transformers import pipeline  # imported late so --help works without the package

    asr = pipeline("automatic-speech-recognition", model=args.model)
    totals = defaultdict(lambda: [0, 0])
    rows = []
    for it in items:
        t0 = time.time()
        heard = asr(it["path"])["text"].strip()
        ref, hyp = words(it["text"]), words(heard)
        edits = edit_distance(ref, hyp)
        key = (it["engine"], it["voice"], it["group"])
        totals[key][0] += edits
        totals[key][1] += len(ref)
        rows.append({**it, "heard": heard, "edits": edits, "ref_words": len(ref), "wer": round(edits / len(ref), 3)})
        print(f"[{it['engine']} | {it['voice']} | {it['id']}] ({time.time() - t0:.1f}s)\n  read:  {it['text']}\n  heard: {heard}"
              f"   -> {edits}/{len(ref)} words wrong", flush=True)

    print("\n=== summary (wrong words / reference words) ===")
    summary = []
    for (engine, voice, group), (edits, n) in sorted(totals.items()):
        print(f"{engine:26s} {voice:10s} {group:10s} {edits:3d}/{n:<3d} = {edits / n:5.0%}")
        summary.append({"engine": engine, "voice": voice, "group": group, "edits": edits, "ref_words": n,
                        "wer": round(edits / n, 3)})
    Path(args.out).write_text(json.dumps({"model": args.model, "summary": summary, "rows": rows},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    print("results:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
