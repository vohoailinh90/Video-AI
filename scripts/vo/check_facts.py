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
  * the page's code is held to what the template uses: its elements and attributes, the names and characters of its script, the
    properties of its style, and no file but its own gsap.min.js (byte for byte). Anything else is refused as code that could put
    words on the screen or load more code. This reads text: the gate does not look at what an image, a video or a sound file holds;
  * the `allow` array of voiceover.json may list only Vietnamese words typed without diacritics from VIETNAMESE_WORDS; a name added
    there would escape the comparison with the digest, so it is refused (the operator's --allow is not limited);
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
import unicodedata
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
# What the page's code may contain: exactly what the video template uses, and nothing else. Everything outside these lists is refused,
# so a way of putting words on the screen that nobody has thought of yet (a style, a script API, a tag, an attribute) is refused too.
# scripts/radar/compose.py writes pages that stay inside them; the committed hand-made pilot does as well (tests check both).
# Not covered, and cannot be by reading text: what an image, a video or a sound file contains.
TEMPLATE_TAGS = {"audio", "b", "body", "div", "em", "h1", "h2", "head", "html", "i", "meta", "p", "script", "section", "small", "span",
                 "strong", "style"}
TEMPLATE_ATTRIBUTES = {"*": {"id", "class", "style", "lang"}, "audio": {"src"}, "script": {"src"}, "meta": {"charset", "name", "content"}}
# the data-* attributes of the template (HyperFrames reads data-composition-src and the like to load other files, so not just any
# data-* is allowed)
TEMPLATE_DATA = {"data-composition-id", "data-duration", "data-height", "data-label", "data-start", "data-track-index", "data-volume",
                 "data-width"}
JS_NAMES = {"E", "__timelines", "arrow", "at", "clipPath", "const", "delay", "draw", "dur", "duration", "ease", "end", "fadeOut", "forEach",
            "from", "fromTo", "gsap", "i", "id", "opacity", "paused", "pop", "rise", "scale", "scaleX", "seek", "sel", "set", "timeline",
            "tl", "to", "true", "window", "x", "y", "yPercent"}     # and S1, S2 ... (scene start times)
JS_TOKEN = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|//[^\n]*|/\*.*?\*/", re.S)   # a string or a comment
CSS_PROPERTIES = {
    "align-items", "background", "border", "border-bottom", "border-color", "border-left", "border-left-color", "border-radius", "border-top",
    "bottom", "box-sizing", "color", "content", "display", "flex", "flex-direction", "flex-wrap", "font-family", "font-size", "font-style",
    "font-weight", "gap", "height", "inset", "justify-content", "left", "letter-spacing", "line-height", "margin", "margin-right",
    "margin-top", "max-width", "min-height", "min-width", "opacity", "overflow", "overflow-wrap", "padding", "padding-bottom",
    "padding-top", "position", "right", "top", "transform-origin", "vertical-align", "white-space", "width"}    # and custom properties --x
CSS_FUNCTIONS = {"linear-gradient", "radial-gradient", "rgba", "var"}      # image-set(), url(), element() ... can load or draw a picture
INLINE_PROPERTIES = {"font-size"}                                        # what the template sets inline; display, opacity, left ... could hide a row
# The only file a page may load: the template's GSAP, named exactly so and identical to the copy vendored in scripts/radar/assets.
# Any other file next to the page (a script, a stylesheet) is code this check does not read, so it is refused.
TRUSTED_SCRIPT = "gsap.min.js"
TRUSTED_COPY = Path(__file__).resolve().parents[1].joinpath("radar", "assets", TRUSTED_SCRIPT)
LOCAL_FILE = re.compile(r"(?!\.\.?/)[\w.\-]+(?:/[\w.\-]+)*")      # a file next to the page: no scheme, no leading /, no ..

# Vietnamese words that have no diacritic and so look like Latin names to this check. A voiceover.json `allow` may list only these:
# the list is part of the check, not of the document being checked, because a name added to `allow` would not be compared with the digest
# at all. A name has to come from the digest.
VIETNAMESE_WORDS = frozenset("""
a ai an anh ao ba bac bai ban bang bao bat bay be ben bi bo bon bu ca cac cai cam can cao cap cat cau ce cha chi cho chu co cua cu cung
da dai dan dao day de den di dia do don du dung em ga gan gi gia giao gio ha hai han hay he hen hi ho hoa hon hu khi kho khu la lai
lam lan lao le len li lo loa loi ma mai man mang mau may me men mi mo mua mui na nam nao nay ne nen nga ngu nha nhe nhi nho nhu no noi
nu nua oi pha phai phi pho phu qua que quan ra rai ram ro ru sa sach sai san sao se si so soi su ta tai tam tan tao tay te ten thi tho
thu ti to toi tu tua tui va vai van vao ve vi vo vua xa xe xi xo xu y yeu
""".split())


# a number, with its sign when a minus or plus stands in front of it (-19, −3,5, +19%; a hyphen after a letter or digit, as in AGPL-3.0
# or 10-20, and a plus after one, as in 1+1 or x+5, are not signs) and with its unit when it is a percentage (19%, 19 %, 19 phần trăm)
NUMBER = re.compile(r"(?:(?<![\w.,\-−+])[-−+])?\d[\d.,]*(?:\s?%|\s+phần trăm\b)?")
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
        self.look_at_code(tag, attrs)
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

    def look_at_code(self, tag, attrs):
        if tag not in TEMPLATE_TAGS:
            self.code.append(f"<{tag}>, which the template never uses")
            return
        names = [name for name, _ in attrs]
        for name in sorted({n for n in names if names.count(n) > 1}):       # dict() would keep the last, a browser keeps the first
            self.code.append(f"the attribute {name} twice on <{tag}>")
        for name, value in dict(attrs).items():
            if name in TEMPLATE_DATA or name in TEMPLATE_ATTRIBUTES["*"] or name in TEMPLATE_ATTRIBUTES.get(tag, ()):
                if name == "style":
                    self.code += [f"an inline style that sets {problem}" for problem in css_problems(value or "", inline=True)]
                elif name == "src" and tag == "script":
                    if value == TRUSTED_SCRIPT:
                        self.scripts.append(value)
                    else:
                        self.code.append(f"<script src=...> that is not the template's {TRUSTED_SCRIPT}")
                elif name == "src" and not LOCAL_FILE.fullmatch((value or "").strip()):
                    self.code.append(f"<{tag} src=...> that is not a file next to the page")
            else:
                self.code.append(f"the attribute {name} on <{tag}>, which the template never uses")

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
        if inside and inside[-1] == "script":
            self.code += [f"script that uses {problem}" for problem in js_problems(data)]
        elif inside:
            self.code += [f"a style that sets {problem}" for problem in css_problems(data)]
        for entry in reversed(self.stack):
            if entry[2] is not None:          # inside a data-label element: held back until we know it is a fixed label
                entry[2].append(text)
                return
        if not any(entry[1] for entry in self.stack):
            self.parts.append(text)


def js_problems(js: str) -> list:
    """What an inline script uses that the template's script does not: a name, a character, a quoted property name, a bracket."""
    problems, code, pos = [], [], 0
    for token in JS_TOKEN.finditer(js):
        code.append(js[pos:token.start()])
        pos = token.end()
        text = token.group(0)
        if text[0] in "\"'":
            code.append('""')
            if re.match(r"\s*:", js[pos:]) and text[1:-1] != "--tip":       # a quoted property name could be innerHTML
                problems.append(f"the property name {text}")
        else:
            code.append(" ")                                                   # a comment
    code.append(js[pos:])
    code = re.sub(r"\b\d[\d.]*", "0", "".join(code)).replace('__timelines[""]', "__timelines")
    code = re.sub(r'(?<![\w$)\]])\[\s*""(?:\s*,\s*"")*\s*\]', '""', code)       # a list of selectors; name[...] is not one
    for name in sorted(set(re.findall(r"[A-Za-z_$][\w$]*", code))):
        if name not in JS_NAMES and not re.fullmatch(r"S\d+", name):
            problems.append(f"the name `{name}`")
    rest = re.sub(r"[A-Za-z_$][\w$]*|\d+", " ", code)
    problems += [f"the character `{char}`" for char in sorted(set(re.findall(r"[^\s(){},;:.=>+\-*/|\"]", rest)))]
    return problems


def css_problems(css: str, inline: bool = False) -> list:
    """What a style sets that the template's style does not: a property outside the list, a content that is not empty, @-rules, url()."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    problems = []
    if "@" in css:
        problems.append("an @-rule")
    if re.search(r"url\s*\(|expression\s*\(|\\", css, re.I):
        problems.append("url(), expression() or an escape")
    body = css if inline else ";".join(re.findall(r"\{([^{}]*)\}", css))
    for function in sorted({f.lower() for f in re.findall(r"([A-Za-z_-][\w-]*)\s*\(", body)} - CSS_FUNCTIONS):
        problems.append(f"the function `{function}()`")
    for declaration in body.split(";"):
        if ":" not in declaration:
            continue
        prop, value = (part.strip() for part in declaration.split(":", 1))
        prop = prop.lower()
        if inline and prop not in INLINE_PROPERTIES:
            problems.append(f"the property `{prop}`")
        elif not (prop in CSS_PROPERTIES or prop.startswith("--")):
            problems.append(f"the property `{prop}`")
        elif prop == "content" and value not in ('""', "''", "none", "normal"):
            problems.append(f"content: {value}")
    return problems


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


NAME = re.compile(r"[a-z0-9_]+(?:[-.][a-z0-9_]+)*(?:\+\+?|#)?")   # faster-whisper-large-v3, bun.sh, AGPL-3.0, C++, C#: a name ends at / : space ...
VERSION_TAIL = re.compile(r"(?:-\d+(?:\.\d+)*)+$")


def names_in(source_blob: str) -> set:
    """Every name the source writes, whole: letters, digits and _ joined by - or . (a / or : or space ends it), and the name before
    a trailing version (AGPL for AGPL-3.0). faster-whisper-large-v3 is one name: faster-whisper and whisper are not in it."""
    names = set()
    for chunk in ascii_chunks(source_blob, need_letter=False):      # not the pieces of a Vietnamese word: c in công is not the name C
        for name in NAME.findall(chunk.lower()):
            names.add(name)
            names.add(VERSION_TAIL.sub("", name))
    names.discard("")
    return names


def has_name(token: str, names: set, source_blob: str) -> bool:
    """The token is a name the source writes. A token of several names (github.com/debpalash/VoiceStudio, setup:api) must also be
    written that way in the source, as a whole: its parts turning up separately somewhere do not make an address up."""
    low = token.lower()
    parts = NAME.findall(low)
    if not parts or not all(part in names for part in parts):
        return False
    if len(parts) == 1:
        return True
    return re.search(rf"(?<![a-z0-9_]){re.escape(low)}(?![a-z0-9_])", source_blob) is not None


def canonical(number: str) -> str:
    """A number as a value: 62.958 and 62,958 (thousands, a first group of 1-3 digits not starting with 0, then groups of exactly
    three) are 62958; 3.14 and 3,14 stay one decimal number, 3.14, and never become 314. A minus or plus sign and a percent sign belong
    to the value: -19 is not 19, +19% is not 19%, and 19% (or 19 phần trăm) is not 19."""
    sign = "-" if number[:1] in "-−" else "+" if number[:1] == "+" else ""
    percent = "%" if re.search(r"%|phần trăm", number) else ""
    number = re.sub(r"\s?%$|\s+phần trăm$", "", number.lstrip("-−+")).rstrip(".,")
    if re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", number):
        return sign + re.sub(r"[.,]", "", number) + percent
    return sign + number.replace(",", ".") + percent


def numbers(text: str) -> set:
    return {canonical(n) for n in NUMBER.findall(text)} - {""}


def ascii_chunks(text: str, need_letter: bool = True):
    """The chunks of a text made only of ASCII (names, acronyms, commands, addresses; a chunk ends at a space or at one of SPLIT).
    A character outside ASCII that is not a letter (a symbol like (tm) or an emoji, a zero-width or combining mark) ends a word and
    hides nothing; a non-ASCII letter makes the chunk a Vietnamese word (only its runs of five or more ASCII letters are kept)."""
    text = "".join(c if ord(c) < 128 or unicodedata.category(c)[0] == "L" else " " for c in unicodedata.normalize("NFC", text))
    for chunk in SPLIT.split(text):
        chunk = chunk.strip(".:,;")
        if re.search(r"[^\x00-\x7f]", chunk):
            # A Vietnamese word, or a name with a letter glued on (ElevenLabsé). No Vietnamese syllable has five ASCII letters in a
            # row, so a run of that length in such a chunk is a name; shorter runs are pieces of a word and are not compared.
            yield from re.findall(r"[A-Za-z]{5,}", chunk)
        elif chunk and (not need_letter or re.search(r"[A-Za-z]", chunk)):
            yield chunk


def latin_tokens(text: str, allow: set) -> list:
    """Chunks made only of ASCII letters/digits/punctuation that look like a name, acronym, command or URL."""
    return [chunk for chunk in ascii_chunks(text) if len(chunk) >= 2 and chunk.lower() not in allow]


def untraced(text: str, source_blob: str, allow: set) -> list:
    problems = []
    known = numbers(source_blob)
    for number in sorted(numbers(text)):
        if number not in known:
            problems.append(f"number {number}")
    names = names_in(source_blob)
    for token in latin_tokens(text, allow):
        if not has_name(token, names, source_blob):
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
    document_allow = {w.lower() for w in doc.get("allow", [])}
    allow = {w.lower() for w in args.allow} | document_allow         # --allow is the operator's; the document's own list is vetted
    failures = 0
    unvetted = sorted(document_allow - VIETNAMESE_WORDS)
    if unvetted:
        print(f"{args.lines}: `allow` lists {', '.join(unvetted)}, which are not Vietnamese words typed without diacritics that this check "
              f"knows; a name has to come from the digest (or the operator passes --allow)")
        failures += 1

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
