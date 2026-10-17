"""Plan a video from one GitHub Radar digest (its draft-vi.json): which fields become scenes, narration and on-screen items.

Nothing here calls a model. The narration is the digest's own sentences (the fields github-radar already gated), cleaned of code
backticks and, for the synthesizer only, with numbers spelled out. What is shown on screen is the same field text, so a number, a name or
a command can only come from the digest. A person may reword a line afterwards in voiceover.json; scripts/vo/check_facts.py then
decides whether the new wording still traces to the cited fields.

A digest becomes up to five scenes, each made of units (one narration clip plus one on-screen item):

  cover    hook (with the repo name)              chips: stars, forks, license, language, scan date
  problem  the sentences of `problem`             the opening one as a pain card, the one that names the tool as the solution
  how      each step of `how_it_works`            nodes joined by arrows, then the components row
  learn    each `learn` item                      cards
  end      each caveat, then the try_it note      caveat cards and a terminal with the try_it commands (at most 6; a digest
                                                          with commands but nothing to narrate still gets this scene)

When the narration would run past the speech budget, groups are cut in a fixed order (see select_units).
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from check_facts import MAX_COMMANDS_SHOWN
from numbers_vi import speak_text

CHARS_PER_SECOND = 19.0   # measured on the Hai Dang narration of videos/voicestudio
CLIP_PAD = 0.2
LEAD, GAP, TAIL = 0.6, 0.5, 1.1   # seconds before the first clip of a scene, between clips, after the last clip
COVER_MIN = 5.2
HOW_COMPONENTS_TAIL = 1.9
END_TAIL = 2.0
TERMINAL_HOLD = 1.0          # seconds the finished terminal stays after its last command is typed
TERM_FIRST, TERM_STEP, TERM_TYPE = 0.9, 0.5, 0.5   # after the heading, between commands, and the time one command takes to type

SCENE_ORDER = ["cover", "problem", "how", "learn", "end"]
MAX_STEPS, MAX_LEARN, MAX_CAVEATS, MAX_COMPONENTS = 4, 3, 2, 6
MAX_COMMANDS = MAX_COMMANDS_SHOWN   # one number for the generator and for the gate that checks `commands_shown`


def clean(text) -> str:
    """Digest text as it is read and shown: no code backticks, one space between words."""
    return re.sub(r"\s+", " ", str(text or "").replace("`", "")).strip()


def split_sentences(text: str) -> list:
    """Split after . ! ? when a capital letter follows; keeps 'AGPL-3.0.' and 'v2.1' in one piece."""
    text = clean(text)
    parts, last = [], 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        following = text[match.end():match.end() + 1]
        if following.isupper():
            parts.append(text[last:match.start()])
            last = match.end()
    parts.append(text[last:])
    return [p for p in parts if p]


def thousands(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def estimate(text: str) -> float:
    return len(speak_text(clean(text))) / CHARS_PER_SECOND + CLIP_PAD


def load_digest(path) -> dict:
    digest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(digest.get("draft"), dict) or not isinstance(digest.get("facts"), dict):
        raise ValueError("not a radar digest: draft-<lang>.json must have `draft` and `facts`")
    if digest.get("lang", "vi") != "vi":
        raise ValueError(f"only Vietnamese digests are supported (VieNeu-TTS reads Vietnamese); this one is {digest.get('lang')!r}")
    for key in ("title", "how_it_works"):
        if not digest["draft"].get(key):
            raise ValueError(f"the digest has no `{key}`")
    if not digest["facts"].get("full_name") or "/" not in digest["facts"]["full_name"]:
        raise ValueError("facts.full_name (owner/repo) is missing")
    url = clean(digest["facts"].get("url"))
    if not re.match(r"https?://\S+$", url):
        raise ValueError("facts.url (the repository address, set by github-radar) is missing; the video shows it and does not make one up")
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc or "?" in url or "#" in url:
        # the digest is copied into the project and its address is put on screen: a secret in it (user:token@host, ?access_token=...,
        # #token) would be committed. The value is not repeated in the message.
        raise ValueError("facts.url has a user name, password, query or fragment in it; github-radar's html_url never does, "
                         "so this digest is not used")
    return digest


def repo_name(digest) -> str:
    return digest["facts"]["full_name"].split("/", 1)[1]


def candidate_units(digest) -> list:
    """Every unit the digest can supply, in play order: dicts with key, scene, text, source."""
    draft, facts = digest["draft"], digest["facts"]
    name = repo_name(digest)
    units = []
    hook = clean(draft.get("hook") or draft.get("one_liner") or draft.get("title"))
    units.append({"key": "hook", "scene": "cover", "text": f"{name}. {hook}",
                  "source": ["facts.full_name", "draft.hook" if draft.get("hook") else "draft.one_liner" if draft.get("one_liner") else "draft.title"]})
    sentences = split_sentences(draft.get("problem", ""))
    for i, sentence in enumerate(sentences):
        units.append({"key": f"problem:{i}", "scene": "problem", "text": sentence, "source": ["draft.problem"]})
    for i, step in enumerate(draft["how_it_works"].get("steps") or []):
        units.append({"key": f"step:{i}", "scene": "how", "text": clean(step.get("text")), "title": clean(step.get("title")),
                      "source": [f"draft.how_it_works.steps[{i}]"]})
    for i, item in enumerate(draft.get("learn") or []):
        units.append({"key": f"learn:{i}", "scene": "learn", "text": clean(item), "source": [f"draft.learn[{i}]"]})
    for i, item in enumerate(draft.get("caveats") or []):
        units.append({"key": f"caveat:{i}", "scene": "end", "text": clean(item), "source": [f"draft.caveats[{i}]"]})
    try_it = draft.get("try_it") or {}
    if clean(try_it.get("note")):
        units.append({"key": "try", "scene": "end", "text": clean(try_it["note"]), "source": ["draft.try_it"]})
    return [u for u in units if u["text"]]


def solution_index(sentences, name) -> int:
    """The sentence of `problem` that presents the tool: the first after the opening one that names it, else the last."""
    for i in range(1, len(sentences)):
        if name.lower() in sentences[i].lower():
            return i
    return len(sentences) - 1


def select_units(candidates, speech_seconds, name="") -> tuple:
    """Pick units within the speech budget. Returns (keys, estimated seconds, note).

    Start from: hook, the opening sentence of the problem and the one that presents the tool, up to 4 steps, 3 learn items,
    2 caveats, the try note.
    While over budget cut, in this order: caveats to 1, learn items to 2, the try note, steps to 3. The hook, the problem, three
    steps and one caveat are never cut; if that is still too long the note says so.
    """
    by_scene = {}
    for unit in candidates:
        by_scene.setdefault(unit["key"].split(":")[0], []).append(unit)
    problem = by_scene.get("problem", [])
    if len(problem) > 2:
        problem = [problem[0], problem[solution_index([u["text"] for u in problem], name)]]
    limits = {"step": MAX_STEPS, "learn": MAX_LEARN, "caveat": MAX_CAVEATS, "try": 1}

    def chosen():
        out = by_scene.get("hook", []) + problem
        for group in ("step", "learn", "caveat", "try"):
            out += by_scene.get(group, [])[:limits[group]]
        return out

    def seconds():
        return sum(estimate(u["text"]) for u in chosen())

    for group, floor in (("caveat", 1), ("learn", 2), ("try", 0), ("step", 3)):
        if seconds() > speech_seconds:
            limits[group] = min(limits[group], floor)
    total = seconds()
    note = None if total <= speech_seconds else f"over the speech budget: about {total:.0f} s of narration against {speech_seconds:.0f} s"
    return [u["key"] for u in chosen()], total, note


def build_plan(digest, selection=None, speech_seconds=60.0) -> dict:
    """The video's content. `selection` (unit keys, as in voiceover.json) overrides the budget choice."""
    candidates = candidate_units(digest)
    note = None
    if selection is None:
        selection, _, note = select_units(candidates, speech_seconds, repo_name(digest))
    unknown = [k for k in selection if k not in {u["key"] for u in candidates}]
    if unknown:
        raise ValueError(f"units not in the digest: {unknown}")
    chosen = [u for u in candidates if u["key"] in set(selection)]

    try_it = digest["draft"].get("try_it") or {}
    all_commands = [clean(c) for c in (try_it.get("commands") or []) if clean(c)]
    commands = all_commands[:MAX_COMMANDS]
    if len(all_commands) > MAX_COMMANDS:
        note = (note + "; " if note else "") + f"try_it has {len(all_commands)} commands, the terminal shows the first {MAX_COMMANDS}"

    units, scenes = [], []
    for scene_id in SCENE_ORDER:
        members = [u for u in chosen if u["scene"] == scene_id]
        if not members:
            if scene_id == "end" and commands:       # a terminal with no caveat and no note to narrate still needs its scene
                scenes.append({"id": "end", "units": []})
            continue
        ids = []
        for unit in members:
            unit = dict(unit)
            unit["id"] = f"vo-{len(units) + 1}"
            spoken = speak_text(unit["text"])
            if spoken != unit["text"]:
                unit["speak"] = spoken
            unit["est"] = round(estimate(unit["text"]), 2)
            units.append(unit)
            ids.append(unit["id"])
        scenes.append({"id": scene_id, "units": ids})
    by_key = {u["key"]: u for u in units}

    draft, facts = digest["draft"], digest["facts"]
    title = clean(draft["title"])
    subtitle = title.split(": ", 1)[1] if ": " in title else title
    chips = []
    if facts.get("stars") is not None:
        chips.append({"value": thousands(facts["stars"]), "label": "sao"})
    if facts.get("forks") is not None:
        chips.append({"value": thousands(facts["forks"]), "label": "fork"})
    for field in ("license", "language"):
        value = clean(facts.get(field))
        if value and value.upper() != "NOASSERTION":
            chips.append({"value": value, "label": None})

    def items(prefix, field="text"):
        return [{"uid": u["id"], "text": u[field]} for u in units if u["key"].split(":")[0] == prefix]

    plan = {
        "name": repo_name(digest),
        "full_name": facts["full_name"],
        "subtitle": subtitle,
        "chips": chips,
        "scan": clean(facts.get("scanned")),
        "url_text": re.sub(r"^https?://", "", clean(facts.get("url"))).rstrip("/"),
        "problem": items("problem"),
        "steps": [{"uid": u["id"], "title": u["title"] or u["text"]} for u in units if u["scene"] == "how"],
        "components": [{"name": clean(c.get("name")), "evidence": clean(c.get("evidence"))}
                       for c in (draft["how_it_works"].get("components") or []) if clean(c.get("name"))][:MAX_COMPONENTS],
        "learn": items("learn"),
        "caveats": items("caveat"),
        "try": {"uid": by_key["try"]["id"] if "try" in by_key else None, "commands": commands,
                "note": by_key["try"]["text"] if "try" in by_key else None} if (commands or "try" in by_key) else None,
        "units": units,
        "scenes": scenes,
        "note": note,
    }
    return plan


SCENE_LABELS = {"cover": "Mở đầu: tên và số liệu", "problem": "Vấn đề nó giải quyết", "learn": "Học được gì từ thiết kế này",
                "caveat": "Lưu ý trước khi dùng", "try": "Tự thử"}


def unit_label(plan, unit) -> str:
    kind = unit["key"].split(":")[0]
    if kind == "step":
        order = [u["id"] for u in plan["units"] if u["scene"] == "how"].index(unit["id"]) + 1
        return f"Cách chạy, bước {order}"
    return SCENE_LABELS.get(kind, SCENE_LABELS.get(unit["scene"], unit["scene"]))


def terminal_head_at(plan, clips, start) -> float:
    """When the "Tự thử" heading appears: before the note is read, else after the last caveat, else at the start of the scene."""
    if plan["try"]["uid"]:
        return clips[plan["try"]["uid"]]["start"] - 0.9
    if plan["caveats"]:
        return clips[plan["caveats"][-1]["uid"]]["end"] + 0.3
    return start + 0.4


def terminal_command_at(head_at, index) -> float:
    return head_at + TERM_FIRST + TERM_STEP * index


def terminal_done_at(plan, clips, start) -> float:
    last = len(plan["try"]["commands"]) - 1
    return terminal_command_at(terminal_head_at(plan, clips, start), last) + TERM_TYPE


def timeline(plan, durations) -> dict:
    """Place every clip and scene. durations: unit id -> seconds. Returns {scenes: [{id, start, end}], clips: {id: {start, end}}, duration}."""
    scenes, clips, now = [], {}, 0.0
    for scene in plan["scenes"]:
        start, cursor = now, now
        if not scene["units"]:
            cursor += LEAD
        for index, uid in enumerate(scene["units"]):
            cursor += LEAD if index == 0 else GAP
            clips[uid] = {"start": round(cursor, 2), "end": round(cursor + durations[uid], 2)}
            cursor += durations[uid]
        if scene["id"] == "how":
            tail = TAIL + (HOW_COMPONENTS_TAIL if plan["components"] else 0)
        elif scene["id"] == "end":
            tail = END_TAIL
        else:
            tail = TAIL
        end = cursor + tail
        if scene["id"] == "end" and plan["try"] and plan["try"]["commands"]:
            end = max(end, terminal_done_at(plan, clips, start) + TERMINAL_HOLD)   # every command typed, then a moment to read
        if scene["id"] == "cover":
            end = max(end, start + COVER_MIN)
        scenes.append({"id": scene["id"], "start": round(start, 2), "end": round(end, 2)})
        now = round(end, 2)
    return {"scenes": scenes, "clips": clips, "duration": now}


def format_plan(plan) -> str:
    lines = [f"{plan['full_name']}: {len(plan['units'])} narration clips, about {sum(u['est'] for u in plan['units']):.0f} s of speech"]
    for scene in plan["scenes"]:
        lines.append(f"  [{scene['id']}]")
        for uid in scene["units"]:
            unit = next(u for u in plan["units"] if u["id"] == uid)
            lines.append(f"    {uid} {unit['key']:<10} ~{unit['est']:>4.1f} s  {unit['text'][:90]}")
    if plan["note"]:
        lines.append(f"  NOTE: {plan['note']}")
    return "\n".join(lines)
