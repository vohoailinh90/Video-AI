"""Synthesize narration clips with VieNeu-TTS (CPU/ONNX) from a voiceover.json file.

Writes one <id>.wav per line (48 kHz mono) and a manifest.json that roundtrip.py and revoice.py understand. A line's `speak`,
when it has one, is what is synthesized (and what roundtrip.py compares against); `text` is what the viewer reads.
Synthesis is sampled, so two runs give slightly different clips: use --only to redo a single line until it checks out.

usage:
  python -I scripts/vo/synth.py --list-voices
  python -I scripts/vo/synth.py --lines videos/demo-video/voiceover.json --out build/voices/hai-dang        # default voice: Hải Đăng
  python -I scripts/vo/synth.py --lines ... --voice "Mai Anh" --out build/voices/mai-anh --only vo-2

Needs the packages in scripts/vo/requirements-tts.txt. First run downloads the model from Hugging Face; if loading then fails
with "External data path escapes model directory", run scripts/vo/fix_hf_cache.py once and run this again with HF_HUB_OFFLINE=1.
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_VOICE = "Hải Đăng"  # the owner's default narrator (male, northern); pass --voice for another


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", help="voiceover.json with the lines to read")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="preset voice name, for example 'Mai Anh' or 'Hải Đăng' (default: %(default)s)")
    ap.add_argument("--out", help="output directory for the wav files and manifest.json")
    ap.add_argument("--only", help="comma-separated line ids to (re)generate; the others in an existing manifest are kept")
    ap.add_argument("--list-voices", action="store_true", help="print the preset voices and exit")
    args = ap.parse_args()

    from vieneu import Vieneu  # imported late so --help works without the package

    tts = Vieneu()
    if args.list_voices:
        for label, name in tts.list_preset_voices():
            print(f"{name:18s} {label}")
        return 0
    if not (args.lines and args.voice and args.out):
        ap.error("--lines, --voice and --out are required")

    import soundfile as sf

    lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))["lines"]
    wanted = set(args.only.split(",")) if args.only else None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    entries = {}
    if manifest_path.exists():
        entries = {e["id"]: e for e in json.loads(manifest_path.read_text(encoding="utf-8"))}

    for line in lines:
        if wanted and line["id"] not in wanted:
            continue
        spoken = line.get("speak", line["text"])  # numbers spelled out by numbers_vi.py; check_facts.py refuses any other `speak`
        audio = tts.infer(spoken, voice=args.voice)
        path = out / f"{line['id']}.wav"
        tts.save(audio, str(path))
        info = sf.info(str(path))
        seconds = info.frames / info.samplerate
        entries[line["id"]] = {
            "engine": "vieneu-v3-turbo", "voice": args.voice, "id": line["id"], "group": "narration",
            "text": spoken, "path": str(path), "audio_seconds": round(seconds, 3), "sample_rate": info.samplerate,
        }
        print(f"{line['id']}: {seconds:.2f} s, {info.samplerate} Hz, {info.channels} ch", flush=True)

    order = [l["id"] for l in lines]
    ordered = [entries[i] for i in order if i in entries]
    manifest_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
    print("manifest:", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
