"""The id of a line of voiceover.json is the stem of its clip: synth.py writes <id>.wav, revoice.py and roundtrip.py read and copy it.

An id is joined to a directory as `directory / f"{id}.wav"`. Joining `/tmp/target` replaces the directory and `../../x` leaves it, so a
line id that is not a plain file name would make these scripts write or read a file anywhere the process can. voiceover.json is edited by
hand and by scripts, so the scripts that join an id check it first, before anything is written.

Stand-alone and standard library only: synth.py runs under `python -I` in the TTS environment, and the scripts that use this file put its
folder on sys.path themselves (`-I` does not add the script's folder).
"""
import re

LINE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")      # letters, digits, - and _; no slash, no `..`, no drive, no dot


def bad_line_ids(lines) -> list:
    """The ids of the lines that are not a plain file name stem (anything but a string of that shape, so a number or a null as well)."""
    return [line.get("id") if isinstance(line, dict) else line
            for line in lines if not isinstance(line, dict) or not isinstance(line.get("id"), str) or not LINE_ID.fullmatch(line["id"])]


def duplicate_line_ids(lines) -> list:
    """The ids that more than one line has. Compared without regard to case: vo-1 and VO-1 are one file on a disk that ignores case."""
    seen, repeated = set(), []
    for line in lines:
        if isinstance(line, dict) and isinstance(line.get("id"), str):
            key = line["id"].casefold()
            if key in seen and line["id"] not in repeated:
                repeated.append(line["id"])
            seen.add(key)
    return repeated


def require_file_name_ids(lines):
    """Stop the script, before it writes anything, when a line id is not a plain file name, or when two lines have the same one (they would
    share a clip: the later line overwrites the earlier one's file, and only the later is heard). The ids are shown with repr()."""
    bad = bad_line_ids(lines)
    if bad:
        raise SystemExit(f"error: a line id is the name of its clip file (letters, digits, - and _), not {bad[:3]!r}")
    repeated = duplicate_line_ids(lines)
    if repeated:
        raise SystemExit(f"error: two lines have the id {", ".join(map(repr, repeated[:3]))}: an id is the name of its clip file, so the later line would overwrite the clip of the earlier")
