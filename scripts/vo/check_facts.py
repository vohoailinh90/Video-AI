"""Check that a video made from a GitHub Radar digest says and shows only what the digest's fields contain.

The source is the digest's draft-vi.json (its gated fields and facts), copied into the video project as source/draft-vi.json.
A script decides, not a model, the way github-radar's gates do:

  * every line of voiceover.json cites the draft fields it comes from (`source`: ["draft.hook", "draft.steps[0]", ...]); each
    path must exist;
  * every number and every Latin-letter token (a name, an acronym, a command) in a line's text must occur in the values of the
    fields that line cites (a number as a value, a token as a whole name: npm is not found in pnpm, faster-whisper is not found in
    faster-whisper-large-v3, and a key such as `license` is not a value; a name before a version, AGPL for AGPL-3.0, is found); Vietnamese words are not compared, because a narration is a shortened rewording, not a copy;
  * the same two checks run on the text a viewer reads in index.html (script, style and elements marked data-label, the template's
    fixed labels, are skipped), against the whole source;
  * the page's code is not read, but the plain ways it has of putting words on the screen or bringing in more code are refused
    (CSS `content:`, @import, DOM-writing script, any script or stylesheet other than the template's own gsap.min.js, frames, on*
    attributes).
    That is a pattern check, not a sandbox: code written to hide what it does gets past it, so the diff of the composition is still
    reviewed, and the gate does not look at images, video or audio;
  * a line's `speak` (the text the synthesizer reads) must be exactly the spelled-out form of its `text`, so what is heard is what is
    traced;
  * each command in try_it.commands must appear on screen exactly as the digest gives it, as a row of its own (not inside a longer
    command), as many times as the digest lists it; voiceover.json's `commands_shown`, when present, limits this to the first N
    commands, for a terminal that cannot show them all; N must be what the video can show, min(commands, MAX_COMMANDS_SHOWN), or the
    gate fails.

Numbers are compared without thousands separators (62.958 or 62,958 on screen equals 62958 in the facts) and with their
minus sign and percent sign (-19 is not 19, 19% is not 19). A Vietnamese word typed without
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
from collections import Counter
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
# What a style or a script can do to put words on the screen, or to bring in code that can. The composition does none of it: GSAP
# moves and fades elements that are already in the page. check_facts.py cannot prove arbitrary code harmless (nor read pixels of an
# image), so it refuses the ways code has of writing text and leaves the rest to the review of the composition's diff.
CSS_TEXT = re.compile(r"(?<![\w-])content\s*:(?!\s*(?:\"\"|''|none|normal)\s*(?:[;}!]|$))|@import\b|url\(\s*[\"']?\s*(?:[a-z]+:)?//", re.I)
JS_WRITES = re.compile(r"\b(?:innerHTML|outerHTML|innerText|textContent|insertAdjacentHTML|insertAdjacentText|createTextNode|createElement|"
                       r"createElementNS|appendChild|insertBefore|replaceChildren|replaceWith|setAttribute|nodeValue|DOMParser|eval|Function|"
                       r"import|importScripts|fetch|XMLHttpRequest|WebSocket|Worker|SharedWorker)\b|\bdocument\s*\.\s*write(?:ln)?\b|"
                       r"\b(?:append|prepend)\s*\(|\.\s*(?:text|html)\s*\(")
# The only file a page may load: the template's GSAP, named exactly so and identical to the copy vendored in scripts/radar/assets.
# Any other file next to the page (a script, a stylesheet) is code this check does not read, so it is refused.
TRUSTED_SCRIPT = "gsap.min.js"
TRUSTED_COPY = Path(__file__).resolve().parents[1].joinpath("radar", "assets", TRUSTED_SCRIPT)
FRAMES = {"iframe", "frame", "object", "embed"}


# a number, with its sign when the minus stands in front of it (-19, −3,5; a hyphen after a letter or digit, as in AGPL-3.0 or 10-20, is
# not one) and with its unit when it is a percentage (19%, 19 %, 19 phần trăm)
NUMBER = re.compile(r"(?:(?<![\w.,\-−])[-−])?\d[\d.,]*(?:\s?%|\s+phần trăm\b)?")
SPLIT = re.compile(r"[\s·—–,;()\[\]{}!?\"'“”‘’…→←•|]+")


class Visible(HTMLParser):
    """Text a viewer can read: everything in <body> except script, style and template, and except elements marked data-label whose
    text is exactly one of FIXED_LABELS (the template's own words, not facts about the digest). A data-label element with any other
    text counts as visible text, so the attribute cannot hide anything."""
    SKIP = {"script", "style", "template", "title"}      # not <head>: a browser ends it at the first element that cannot be in it
    VOID = {"br", "img", "meta", "link", "input", "hr", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # [tag, skipped, label buffer or None] for every open element
        self.parts = []
        self.code = []       # problems with the page's code: what it could write, load or run
        self.scripts = []    # the trusted script files the page loads

    def handle_starttag(self, tag, attrs):
        self.look_at_code(tag, dict(attrs))
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

    SHOWN = ("value", "placeholder", "alt", "label")      # attributes whose text a browser can draw (inputs, a broken image, options)

    def look_at_code(self, tag, attrs):
        for name in self.SHOWN:
            text = (attrs.get(name) or "").strip()
            if text and not self.stack_is_hidden():
                self.parts.append(text)
        for name in attrs:
            if name.startswith("on"):
                self.code.append(f"the event handler attribute {name} on <{tag}>")
        if tag in FRAMES:
            self.code.append(f"<{tag}> (it can show a page that is not this one)")
        for name, wanted in (("script", "src"), ("link", "href")):
            if tag == name and attrs.get(wanted) is not None:
                if tag == "script" and attrs[wanted] == TRUSTED_SCRIPT:
                    self.scripts.append(attrs[wanted])
                else:
                    self.code.append(f"<{tag} {wanted}=...> that is not the template's {TRUSTED_SCRIPT}")

    def stack_is_hidden(self):
        return any(entry[1] for entry in self.stack)

    def close(self):
        super().close()
        for _, _, buffer in self.stack[::-1]:      # an element that was never closed still shows what it holds
            if buffer is not None:
                text = " ".join(buffer).strip()
                if text and text not in FIXED_LABELS.values():
                    self.parts.append(text)
        self.stack = []

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        inside = [entry[0] for entry in self.stack if entry[0] in ("script", "style")]
        if inside:
            found = (JS_WRITES if inside[-1] == "script" else CSS_TEXT).search(data)
            if found:
                self.code.append(f"{'script' if inside[-1] == 'script' else 'style'} text `{found.group(0).strip()}`")
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
    """A command as the video shows it: exactly as the digest gives it, without the spaces around it (a command is not prose, so no
    backtick is dropped and no run of spaces is merged: scripts/radar/plan.py does the same)."""
    return str(text or "").strip()


def blob(value) -> str:
    """The text a source holds, lowercased, one value per line: every string and number in it, not its keys (`license` or `commands`
    as a key is structure, not a fact the video may state)."""
    parts = []

    def walk(node):
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        elif node is not None and not isinstance(node, bool):
            parts.append(str(node))

    walk(value)
    return "\n".join(parts).lower()


NAME = re.compile(r"[a-z0-9_]+(?:[-.][a-z0-9_]+)*")           # faster-whisper-large-v3, bun.sh, AGPL-3.0: a name ends at / : space ...
VERSION_TAIL = re.compile(r"(?:-\d+(?:\.\d+)*)+$")


def names_in(source_blob: str) -> set:
    """Every name the source writes, whole: letters, digits and _ joined by - or . (a / or : or space ends it), and the name before
    a trailing version (AGPL for AGPL-3.0). faster-whisper-large-v3 is one name: faster-whisper and whisper are not in it."""
    names = set()
    for name in NAME.findall(source_blob):
        names.add(name)
        names.add(VERSION_TAIL.sub("", name))
    names.discard("")
    return names


def has_name(token: str, names: set) -> bool:
    """The token is made of names the source writes; github.com/debpalash/VoiceStudio is three of them."""
    parts = NAME.findall(token.lower())
    return bool(parts) and all(part in names for part in parts)


def canonical(number: str) -> str:
    """A number as a value: 62.958 and 62,958 (thousands, a first group of 1-3 digits not starting with 0, then groups of exactly
    three) are 62958; 3.14 and 3,14 stay one decimal number, 3.14, and never become 314. A minus sign and a percent sign belong to
    the value: -19 is not 19, and 19% (or 19 phần trăm) is not 19."""
    sign = "-" if number[:1] in "-−" else ""
    percent = "%" if re.search(r"%|phần trăm", number) else ""
    number = re.sub(r"\s?%$|\s+phần trăm$", "", number.lstrip("-−")).rstrip(".,")
    if re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", number):
        return sign + re.sub(r"[.,]", "", number) + percent
    return sign + number.replace(",", ".") + percent


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
    names = names_in(source_blob)
    for token in latin_tokens(text, allow):
        if not has_name(token, names):
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
    parser.close()
    for name in sorted(set(parser.scripts)):         # the one trusted file must really be the template's, not a file with its name
        loaded = Path(args.html).resolve().parent / name
        if not loaded.is_file() or not TRUSTED_COPY.is_file() or loaded.read_bytes() != TRUSTED_COPY.read_bytes():
            parser.code.append(f"<script src={name}> that is not the template's {TRUSTED_SCRIPT} byte for byte")
    if parser.code:
        print(f"{args.html}: code that could put words on the screen or load code, which this check cannot trace: "
              f"{'; '.join(sorted(set(parser.code)))}")
        failures += 1
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
    rows = Counter(parser.parts)    # a command is one row of the page, not a piece of a longer one
    for command, count in Counter(required).items():
        if rows[command] < count:
            print(f"{args.html}: command from try_it is not shown exactly{' ' + str(count) + ' times' if count > 1 else ''}: {command!r}")
            failures += 1

    spoken = sum(len(NUMBER.findall(l["text"])) for l in lines)
    print(f"checked {len(lines)} lines and {len(parser.parts)} on-screen text pieces "
          f"({spoken} numbers in narration): {'FAILED, ' + str(failures) + ' problem(s)' if failures else 'all traced to the source'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
