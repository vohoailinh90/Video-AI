"""Check that a video made from a GitHub Radar digest says and shows only what the digest's fields contain.

The source is the digest's draft-vi.json (its gated fields and facts), copied into the video project as source/draft-vi.json.
A script decides, not a model, the way github-radar's gates do:

  * every line of voiceover.json cites the draft fields it comes from (`source`: ["draft.hook", "draft.steps[0]", ...]); each
    path must exist;
  * every number and every Latin-letter token (a name, an acronym, a command) in a line's text must occur in the fields that line
    cites; Vietnamese words are not compared, because a narration is a shortened rewording, not a copy;
  * the same two checks run on the text a viewer reads in index.html (script, style and elements marked data-label, the template's
    fixed labels, are skipped), against the whole source;
  * a line's `speak` (the text the synthesizer reads) must be exactly the spelled-out form of its `text`, so what is heard is what is
    traced;
  * each command in try_it.commands must appear on screen exactly as the digest gives it (voiceover.json's `commands_shown`, when
    present, limits this to the first N commands, for a terminal that cannot show them all; N must be what the video can show,
    min(commands, MAX_COMMANDS_SHOWN), or the gate fails).

Numbers are compared without thousands separators (62.958 or 62,958 on screen equals 62958 in the facts) and with their
minus sign (-19 is not 19). A Vietnamese word typed without
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

sys.path.insert(0, str(Path(__file__).resolve().parent))  # numbers_vi, next to this file; -I does not add the script's folder
from numbers_vi import speak_text  # noqa: E402

# The video template's own words. An element marked data-label is skipped by the trace only when its text is exactly one of these;
# any other text in such an element is read like the rest of the page. scripts/radar/compose.py takes its labels from here.
FIXED_LABELS = {
    "problem": "Vấn đề nó giải quyết",
    "how": "Nó chạy như thế nào",
    "parts": "Các mảnh ghép",
    "learn": "Học được gì từ thiết kế này",
    "caveats": "Lưu ý trước khi dùng",
    "try": "Tự thử",
    "scan": "Số liệu theo ngày quét",
    "stars": "sao",
    "forks": "fork",
}
MAX_COMMANDS_SHOWN = 6   # the most try_it commands a video's terminal shows; scripts/radar/plan.py takes its cap from here
# a number, with its sign when the minus stands in front of it (-19, −3,5); a hyphen after a letter or a digit (AGPL-3.0, 10-20) is not one
NUMBER = re.compile(r"(?:(?<![\w.,\-−])[-−])?\d[\d.,]*")
SPLIT = re.compile(r"[\s·—–,;()\[\]{}!?\"'“”‘’…→←•|]+")


class Visible(HTMLParser):
    """Text a viewer can read: everything in <body> except script, style and template, and except elements marked data-label whose
    text is exactly one of FIXED_LABELS (the template's own words, not facts about the digest). A data-label element with any other
    text counts as visible text, so the attribute cannot hide anything."""
    SKIP = {"script", "style", "template", "title", "head"}
    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # [tag, skipped, label buffer or None] for every open element
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        is_label = any(name == "data-label" for name, _ in attrs)
        self.stack.append([tag, tag in self.SKIP, [] if is_label else None])

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                for _, _, buffer in self.stack[index:][::-1]:
                    if buffer is not None:
                        text = " ".join(buffer).strip()
                        if text and text not in FIXED_LABELS.values():
                            self.parts.append(text)
                del self.stack[index:]
                return

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        for entry in reversed(self.stack):
            if entry[2] is not None:          # inside a data-label element: held back until we know it is a fixed label
                entry[2].append(text)
                return
        if not any(entry[1] for entry in self.stack):
            self.parts.append(text)


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


def normalize(text) -> str:
    """A command as the video shows it: no code backticks, one space between words (scripts/radar/plan.clean)."""
    return re.sub(r"\s+", " ", str(text or "").replace("`", "")).strip()


def blob(value) -> str:
    return json.dumps(value, ensure_ascii=False).lower()


def canonical(number: str) -> str:
    """A number as a value: 62.958 and 62,958 (thousands, a first group of 1-3 digits not starting with 0, then groups of exactly
    three) are 62958; 3.14 and 3,14 stay one decimal number, 3.14, and never become 314. A minus sign belongs to the value: -19 is
    not 19."""
    sign = "-" if number[:1] in "-−" else ""
    number = number.lstrip("-−").rstrip(".,")
    if re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", number):
        return sign + re.sub(r"[.,]", "", number)
    return sign + number.replace(",", ".")


def numbers(text: str) -> set:
    return {canonical(n) for n in NUMBER.findall(text)} - {""}


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
        if "speak" in line and line["speak"] != speak_text(line["text"]):
            print(f"{line['id']}: `speak` is what the viewer hears and must be the spelled-out form of `text` "
                  f"(numbers_vi.speak_text), not other words; reword `text` instead")
            failures += 1
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
    commands = [normalize(c) for c in source["draft"].get("try_it", {}).get("commands", []) if normalize(c)]
    required = commands
    if doc.get("commands_shown") is not None:      # a video may show only the first N commands, and says so here
        expected = min(len(commands), MAX_COMMANDS_SHOWN)
        if doc["commands_shown"] != expected:      # the claim is checked, not trusted: it cannot shrink the list of commands to find
            print(f"{args.lines}: commands_shown is {doc['commands_shown']!r}, but a video of this digest shows "
                  f"{expected} of its {len(commands)} commands")
            failures += 1
        required = commands[:expected]
    for command in required:
        if command not in screen:
            print(f"{args.html}: command from try_it is not shown exactly: {command!r}")
            failures += 1

    spoken = sum(len(NUMBER.findall(l["text"])) for l in lines)
    print(f"checked {len(lines)} lines and {len(parser.parts)} on-screen text pieces "
          f"({spoken} numbers in narration): {'FAILED, ' + str(failures) + ' problem(s)' if failures else 'all traced to the source'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
