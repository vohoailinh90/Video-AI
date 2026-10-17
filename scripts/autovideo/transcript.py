"""Transcript of a rendered video: the subtitle cues MPT wrote, how well they cover the script, and a start/end for every scene.

Nothing is transcribed from the audio here. The words are the pack's own narration (what the voice was given) and the times are the
subtitle cues' (what MPT measured while it made the voice). `scripts/vo/roundtrip.py` is the tool for listening to the audio again.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .pack import CJK, Job

TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        for i, line in enumerate(lines):
            match = TIME.search(line)
            if match:
                body = " ".join(part.strip() for part in lines[i + 1:])
                if body:
                    g = match.groups()
                    cues.append(Cue(_seconds(*g[:4]), _seconds(*g[4:]), body))
                break
    return cues


def tokens(text: str) -> list[str]:
    """Words, compared without caring about case, punctuation or how a diacritic is encoded. Every CJK character counts as a word."""
    text = unicodedata.normalize("NFC", text).casefold()
    return CJK.findall(text) + re.findall(r"\w+", CJK.sub(" ", text))


def coverage(script: str, cues: list[Cue]) -> float:
    """Share of the script's words that appear in the subtitles (1.0 = all of them)."""
    want = Counter(tokens(script))
    if not want:
        return 1.0
    have = Counter(tok for cue in cues for tok in tokens(cue.text))
    return sum(min(n, have[tok]) for tok, n in want.items()) / sum(want.values())


def scene_times(scenes: list[str], cues: list[Cue]) -> list[tuple[float, float] | None]:
    """Start and end of each scene, found by counting words: scene k owns the k-th share of the words the cues contain.

    Returns None for every scene when the cues and the script differ too much in length for that to mean anything."""
    spoken = [(i, tok) for i, cue in enumerate(cues) for tok in tokens(cue.text)]
    sizes = [len(tokens(scene)) for scene in scenes]
    total = sum(sizes)
    if not spoken or not total or not 0.8 <= len(spoken) / total <= 1.25:
        return [None] * len(scenes)
    out, done = [], 0
    for size in sizes:
        first = round(done * len(spoken) / total)
        last = round((done + size) * len(spoken) / total)
        done += size
        if size == 0 or last <= first:
            out.append(None)
            continue
        a = spoken[min(first, len(spoken) - 1)][0]
        b = spoken[min(last - 1, len(spoken) - 1)][0]
        out.append((cues[a].start, cues[b].end))
    return out


def transcript(job: Job, cues: list[Cue], audio_name: str | None, srt_name: str | None) -> tuple[str, dict]:
    """The plain text file and the JSON document stored next to the video."""
    texts = [scene.narration for scene in job.scenes]
    times = scene_times(texts, cues)
    plain = "\n\n".join(texts) + "\n"
    document = {
        "id": job.id,
        "title": job.title,
        "language": job.language,
        "scenes": [
            {"index": i + 1, "text": text, "start": None if t is None else round(t[0], 3), "end": None if t is None else round(t[1], 3)}
            for i, (text, t) in enumerate(zip(texts, times))
        ],
        "cues": [{"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text} for c in cues],
        "files": {"audio": audio_name, "subtitles": srt_name},
        "note": "words are the pack's narration; times are the subtitle cues' (none when subtitles are off)",
    }
    return plain, document
