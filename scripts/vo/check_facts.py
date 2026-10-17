"""Check that a video made from a GitHub Radar digest says and shows only what the digest's fields contain.

The source is the digest's draft-vi.json (its gated fields and facts), copied into the video project as source/draft-vi.json.
A script decides, not a model, the way github-radar's gates do:

  * every line of voiceover.json cites the draft fields it comes from (`source`: ["draft.hook", "draft.steps[0]", ...]); each
    path must exist;
  * every number and every Latin-letter token (a name, an acronym, a command) in a line's text must occur in the fields that line
    cites; Vietnamese words are not compared, because a narration is a shortened rewording, not a copy;
  * the same two checks run on the text a viewer reads in index.html (script and style are skipped), against the whole source;
  * each command in try_it.commands must appear on screen exactly as the digest gives it.

Numbers are compared without thousands separators (62.958 on screen equals 62958 in the facts). A Vietnamese word typed without
any diacritic (giao, cho, ba) looks like a Latin token and is flagged when the source lacks it; list such a word in the
"allow" array of voiceover.json (or pass --allow).
Single letters are skipped.

usage: python -I scripts/vo/check_facts.py --source videos/voicestudio/source/draft-vi.json \\
           --lines videos/voicestudio/voiceover.json --html videos/voicestudio/index.html [--allow word ...]
exit status: 0 when everything is traced, 1 otherwise (each problem is printed).
"""
import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

NUMBER = re.compile(r"\d[\d.,]*")
SPLIT = re.compile(r"[\s·—–,;()\[\]{}!?\"'“”‘’…→←•|]+")


class Visible(HTMLParser):
    """Text a viewer can read: everything in <body> except script, style and template."""
    SKIP = {"script", "style", "template", "title", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def resolve(root, path):
    """draft.how_it_works.steps[0] -> the object it names (KeyError/IndexError when missing)."""
    node = root
    for part in path.split("."):
        match = re.fullmatch(r"([A-Za-z_]\w*)((?:\[\d+\])*)", part)
        if not match:
            raise KeyError(path)
        node = node[match.group(1)]
        for index in re.findall(r"\[(\d+)\]", match.group(2)):
            node = node[int(index)]
    return node


def blob(value) -> str:
    return json.dumps(value, ensure_ascii=False).lower()


def numbers(text: str) -> set:
    return {re.sub(r"[.,]", "", n.rstrip(".,")) for n in NUMBER.findall(text)} - {""}


def latin_tokens(text: str, allow: set) -> list:
    """Chunks made only of ASCII letters/digits/punctuation that look like a name, acronym, command or URL."""
    out = []
    for chunk in SPLIT.split(text):
        chunk = chunk.strip(".:,;")
        if not chunk or not re.search(r"[A-Za-z]", chunk) or re.search(r"[^\x00-\x7f]", chunk):
            continue
        if len(chunk) < 2 or chunk.lower() in allow:
            continue
        out.append(chunk)
    return out


def untraced(text: str, source_blob: str, allow: set) -> list:
    problems = []
    known = numbers(source_blob)
    for number in sorted(numbers(text)):
        if number not in known:
            problems.append(f"number {number}")
    for token in latin_tokens(text, allow):
        if token.lower() not in source_blob:
            problems.append(f"token {token!r}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="source/draft-vi.json from the digest")
    ap.add_argument("--lines", required=True, help="voiceover.json (lines with text and source)")
    ap.add_argument("--html", required=True, help="index.html of the video")
    ap.add_argument("--allow", nargs="*", default=[], help="Vietnamese ASCII words that are flagged by mistake")
    args = ap.parse_args()

    source = json.loads(Path(args.source).read_text(encoding="utf-8"))
    doc = json.loads(Path(args.lines).read_text(encoding="utf-8"))
    lines = doc["lines"]
    allow = {w.lower() for w in args.allow} | {w.lower() for w in doc.get("allow", [])}
    failures = 0

    for line in lines:
        cited = line.get("source") or []
        if not cited:
            print(f"{line['id']}: no source fields cited")
            failures += 1
            continue
        try:
            fields = [resolve(source, path) for path in cited]
        except (KeyError, IndexError):
            print(f"{line['id']}: a cited field does not exist in the source: {cited}")
            failures += 1
            continue
        problems = untraced(line["text"], blob(fields), allow)
        if problems:
            print(f"{line['id']}: not in the cited fields {cited}: {', '.join(problems)}")
            failures += 1

    parser = Visible()
    parser.feed(Path(args.html).read_text(encoding="utf-8"))
    screen = "\n".join(parser.parts)
    source_blob = blob(source)
    problems = untraced(screen, source_blob, allow)
    if problems:
        print(f"{args.html}: on-screen text not in the source: {', '.join(problems)}")
        failures += 1
    for command in source["draft"].get("try_it", {}).get("commands", []):
        if command not in screen:
            print(f"{args.html}: command from try_it is not shown exactly: {command!r}")
            failures += 1

    spoken = sum(len(NUMBER.findall(l["text"])) for l in lines)
    print(f"checked {len(lines)} lines and {len(parser.parts)} on-screen text pieces "
          f"({spoken} numbers in narration): {'FAILED, ' + str(failures) + ' problem(s)' if failures else 'all traced to the source'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
