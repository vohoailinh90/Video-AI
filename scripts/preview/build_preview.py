"""Build a self-contained preview page for one or more rendered videos (for example one per narration voice).

Why: the claude.ai artifact viewer refused to play a video that was published as a separate file or as an uploaded asset
("No video with supported format and MIME type found"), even though the file itself was a normal H.264/AAC mp4. Putting the
video inside the page as base64 and building the playable source in script worked. This script produces such a page.

The page lists the narration lines (from voiceover.json) as buttons that jump to that point, offers a switch between voices,
and writes a status line that says which source it used or why none worked. For every video it embeds an mp4 and a WebM
(VP9 + Opus) fallback; the WebM is encoded with ffmpeg next to the mp4 when it is missing.

usage: python -I scripts/preview/build_preview.py --config videos/demo-video/preview.json --out build/preview/index.html

preview.json (paths are relative to the json file; the first voice is the one the page opens with):
  { "title": "...", "eyebrow": "...", "lede": "...",
    "lines": "voiceover.json",                     # lines with start, text, scene
    "facts": [["Độ dài", "17 giây"], ...],
    "notes": ["...", "..."],
    "voices": [ { "key": "mai-anh", "label": "Giọng nữ · Mai Anh", "mp4": "renders/demo-video.mp4", "webm": "optional" } ] }

The page must stay under 16 MB for the artifact viewer; keep each video around 2.5 MB (about 5 MB per voice with both formats).
"""
import argparse
import base64
import html
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def encode_webm(mp4: Path, webm: Path) -> None:
    print(f"encoding {webm.name} (VP9 + Opus) ...", flush=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-row-mt", "1",
         "-cpu-used", "4", "-deadline", "good", "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "128k", str(webm)],
        check=True,
    )


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-mb", type=float, default=15.0, help="fail when the page is bigger than this (default: %(default)s)")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    base = config_path.parent
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    lines = json.loads((base / cfg["lines"]).read_text(encoding="utf-8"))["lines"]
    esc = html.escape

    voices_html, media, default_key = [], [], None
    for index, voice in enumerate(cfg["voices"]):
        key = voice["key"]
        if not re.fullmatch(r"[a-z0-9-]+", key):
            raise SystemExit(f"voice key must match [a-z0-9-]+: {key}")
        mp4 = (base / voice["mp4"]).resolve()
        if not mp4.is_file():
            raise SystemExit(f"missing video: {mp4} (render it first)")
        webm = (base / voice["webm"]).resolve() if voice.get("webm") else mp4.with_suffix(".webm")
        if not webm.is_file() or webm.stat().st_mtime < mp4.stat().st_mtime:
            encode_webm(mp4, webm)
        default_key = default_key or key
        voices_html.append(
            f'<button type="button" class="voice" data-voice="{key}" aria-pressed="{"true" if index == 0 else "false"}">'
            f'{esc(voice["label"])}</button>')
        for fmt, path in (("mp4", mp4), ("webm", webm)):
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            media.append(f'<script type="text/plain" id="b64-{key}-{fmt}">{b64}</script>')
            print(f"  {key} {fmt}: {path.stat().st_size / 1e6:.2f} MB")

    voices_block = ""
    if len(voices_html) > 1:
        voices_block = '<div class="voices" role="group" aria-label="Chọn giọng đọc">' + "".join(voices_html) + "</div>"

    facts = "\n".join(f"    <div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in cfg.get("facts", []))
    items = "\n".join(
        f'      <li><button type="button" data-t="{l["start"]:g}"><time>{clock(l["start"])}</time>'
        f'<span class="line">{esc(l["text"])}<span class="scene">{esc(l.get("scene", ""))}</span></span></button></li>'
        for l in lines)
    notes = "\n".join(f'    <p class="note">{esc(n)}</p>' for n in cfg.get("notes", []))

    page = (HERE / "template.html").read_text(encoding="utf-8")
    replacements = {
        "__TITLE__": esc(cfg["title"]), "__EYEBROW__": esc(cfg.get("eyebrow", "")), "__LEDE__": esc(cfg.get("lede", "")),
        "__VOICES__": voices_block, "__FACTS__": facts, "__LINES__": items, "__NOTES__": notes,
        "__DEFAULT_VOICE__": default_key, "__MEDIA__": "\n".join(media),
    }
    for marker, value in replacements.items():
        if marker == "__TITLE__":
            page = page.replace(marker, value)  # appears in <title> and <h1>
            continue
        assert page.count(marker) == 1, marker
        page = page.replace(marker, value)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    size = out.stat().st_size / 1e6
    print(f"{out}  {size:.2f} MB")
    if size > args.max_mb:
        print(f"page is bigger than {args.max_mb} MB: lower the resolution or raise the CRF of the videos", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
