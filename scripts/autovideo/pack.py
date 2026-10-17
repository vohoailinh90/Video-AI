"""Script packs: the files an agent writes (one entry per video) and the renderer reads.

A pack is one JSON file, or a directory with `pack.json` (batch name and defaults) and `videos/<id>.json` (one video each, so several
writers can work at the same time without touching the same file). `load_pack` checks everything it can without a network and without
MoneyPrinterTurbo, and reports every problem at once as `path: message` lines, so a writer fixes them in one pass.

Nothing here decides how a video looks: a pack carries the words, the search terms for stock footage and a few settings.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
LANGUAGE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}$")
VOICE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z0-9-]+$")
FONT = re.compile(r"^[\w .-]+\.(ttf|ttc)$", re.IGNORECASE)  # MPT's CLI refuses any other subtitle font extension, comparing it in lower case

ASPECTS = ("9:16", "16:9", "1:1")
# Only sources that cost nothing per request. MPT also has paid generators (WaveSpeed, Seedance, OFox, ...); each needs its own
# confirmation flag there, and this tool never sets one.
SOURCES = ("pexels", "pixabay", "coverr", "local")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".flv", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".bmp")
# Two lists, because MPT keeps two. Narration (audio_file): _CUSTOM_AUDIO_EXTENSIONS in its cli.py, which refuses the whole manifest for any other
# suffix. Music (bgm): SUPPORTED_BGM_EXTENSIONS in its app/services/bgm.py. Both compare the suffix in lower case.
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
MUSIC_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma")
MUSIC_NAME = re.compile(r"[\w .()-]+(" + "|".join(re.escape(e) for e in MUSIC_EXTENSIONS) + ")", re.IGNORECASE)
NO_VOICE = "no-voice"

SETTINGS = (
    "language", "aspect", "voice", "voice_rate", "voice_volume", "material_source", "materials", "audio_file", "bgm", "bgm_volume",
    "subtitles", "font", "font_size", "clip_seconds", "target_seconds",
)
VIDEO_KEYS = ("id", "title", "scenes", "terms", *SETTINGS)
TOP_KEYS = ("version", "batch", "defaults", "videos")
DIR_TOP_KEYS = ("version", "batch", "defaults")

BUILT_IN = {
    "language": "vi-VN",
    "aspect": "9:16",
    "voice": "vi-VN-HoaiMyNeural",
    "voice_rate": 1.0,
    "voice_volume": 1.0,
    "material_source": "pexels",
    "materials": [],
    "audio_file": None,
    "bgm": "random",
    "bgm_volume": 0.2,
    "subtitles": True,
    "font": None,
    "font_size": 60,
    "clip_seconds": 5,
    "target_seconds": [15, 180],
}

MAX_VIDEOS = 100  # the same cap as MPT's batch manifest
MAX_SCENES = 30
MAX_SCENE_CHARS = 600
MAX_SCRIPT_CHARS = 4000
MAX_TERMS_PER_SCENE = 8

# Fonts that ship in MPT's resource/fonts. The default one for the Vietnamese language has to cover Vietnamese diacritics.
FONT_BY_LANGUAGE = {"zh": "STHeitiMedium.ttc", "ja": "STHeitiMedium.ttc"}
FONT_DEFAULT = "BeVietnamPro-Bold.ttf"

URL = re.compile(r"https?://|www\.|\S+@\S+\.\S+", re.I)
MARKDOWN = re.compile(r"[*#_`~|<>\[\]{}\\]")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


class PackError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass(frozen=True)
class Scene:
    narration: str
    terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    scenes: tuple[Scene, ...]
    extra_terms: tuple[str, ...]
    language: str
    aspect: str
    voice: str
    voice_rate: float
    voice_volume: float
    material_source: str
    materials: tuple[str, ...]
    audio_file: str | None
    bgm: str
    bgm_volume: float
    subtitles: bool
    font: str
    font_size: int
    clip_seconds: int
    min_seconds: float
    max_seconds: float

    @property
    def script(self) -> str:
        """What is read aloud: one scene per line, in order."""
        return "\n".join(scene.narration for scene in self.scenes)

    @property
    def terms(self) -> tuple[str, ...]:
        """Search terms of every scene, then the extra ones, each once, in order."""
        seen: dict[str, None] = {}
        for term in [t for scene in self.scenes for t in scene.terms] + list(self.extra_terms):
            seen.setdefault(term, None)
        return tuple(seen)

    @property
    def reads_aloud(self) -> bool:
        return self.audio_file is None and self.voice != NO_VOICE

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "scenes": [{"narration": s.narration, "terms": list(s.terms)} for s in self.scenes],
            "terms": list(self.extra_terms),
            "language": self.language, "aspect": self.aspect, "voice": self.voice, "voice_rate": self.voice_rate,
            "voice_volume": self.voice_volume, "material_source": self.material_source, "materials": list(self.materials),
            "audio_file": self.audio_file, "bgm": self.bgm, "bgm_volume": self.bgm_volume, "subtitles": self.subtitles,
            "font": self.font, "font_size": self.font_size, "clip_seconds": self.clip_seconds,
            "target_seconds": [self.min_seconds, self.max_seconds],
        }

    @cached_property
    def _file_digests(self) -> list:
        """SHA-256 of every local material and of the audio file. A replaced file of the same size must change the fingerprint
        (equal-length WAV clips are the usual case), so the content is read; once per job, because a run asks many times."""
        digests = []
        for name in [*self.materials, *([self.audio_file] if self.audio_file else [])]:
            try:
                with open(name, "rb") as handle:
                    digests.append([name, hashlib.file_digest(handle, "sha256").hexdigest()])
            except OSError:
                digests.append([name, None])
        return digests

    def fingerprint(self) -> str:
        """Changes when the words or a render setting changes, or a local file is replaced; an edited job renders again."""
        files = self._file_digests
        render_inputs = {k: v for k, v in self.to_dict().items() if k != "target_seconds"}  # a QA limit does not change the render
        blob = json.dumps([render_inputs, files], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def estimate_seconds(self) -> float:
        """Rough reading time of the script. Only for planning: the real length is the length of the audio."""
        text = self.script
        cjk = len(CJK.findall(text))
        words = len(CJK.sub(" ", text).split())
        return round((cjk / 4.5 + words / 2.5) / self.voice_rate + 0.8, 1)


@dataclass
class Pack:
    batch: str
    jobs: list[Job]
    warnings: list[str] = field(default_factory=list)
    root: Path = Path(".")


def _read_json(path: Path, problems: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        problems.append(f"{path}: cannot read: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        problems.append(f"{path}: not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})")
    return None


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _unknown(obj: dict, allowed: tuple[str, ...], where: str, problems: list[str]) -> None:
    for key in obj:
        if key not in allowed:
            problems.append(f"{where}: unknown key {key!r} (allowed: {', '.join(allowed)})")


def _file(value, root: Path, extensions: tuple[str, ...], where: str, problems: list[str], check_files: bool) -> str | None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: must be a file path")
        return None
    path = Path(value).expanduser()
    path = path if path.is_absolute() else root / path
    if path.suffix.lower() not in extensions:
        problems.append(f"{where}: {path.name} is not one of {', '.join(extensions)}")
        return None
    if check_files and not path.is_file():
        problems.append(f"{where}: no such file: {path}")
        return None
    if check_files:
        try:
            open(path, "rb").close()  # a file that is there but cannot be opened would only fail later, inside MPT
        except OSError as exc:
            problems.append(f"{where}: cannot read {path}: {exc.strerror or exc}")
            return None
    return str(path.resolve())


def _settings(raw: dict, root: Path, where: str, problems: list[str], check_files: bool) -> dict:
    """Validate the keys of `raw` that are settings, and return them normalised. Keys that are absent stay absent."""
    out: dict = {}

    def pick(key, ok, message):
        if key in raw:
            if ok(raw[key]):
                out[key] = raw[key]
            else:
                problems.append(f"{where}.{key}: {message}")

    pick("language", lambda v: isinstance(v, str) and LANGUAGE.match(v), "must look like vi-VN or en-US")
    pick("aspect", lambda v: v in ASPECTS, f"must be one of {', '.join(ASPECTS)}")
    pick("voice", lambda v: isinstance(v, str) and (v == NO_VOICE or VOICE.match(v)), f"must be an Edge voice such as vi-VN-HoaiMyNeural, or {NO_VOICE}")
    pick("voice_rate", lambda v: _is_number(v) and 0.5 <= v <= 2.0, "must be a number from 0.5 to 2.0")
    pick("voice_volume", lambda v: _is_number(v) and 0 < v <= 3, "must be a number above 0 and at most 3")
    pick("material_source", lambda v: v in SOURCES, f"must be one of {', '.join(SOURCES)}")
    pick("bgm", lambda v: isinstance(v, str) and v.strip() != "", "must be none, random, or the name of a music file known to MPT")
    pick("bgm_volume", lambda v: _is_number(v) and 0 <= v <= 1, "must be a number from 0 to 1")
    pick("subtitles", lambda v: isinstance(v, bool), "must be true or false")
    pick("font", lambda v: v is None or (isinstance(v, str) and FONT.match(v)), "must be a .ttf or .ttc font file name such as BeVietnamPro-Bold.ttf")
    pick("font_size", lambda v: isinstance(v, int) and not isinstance(v, bool) and 20 <= v <= 200, "must be a whole number from 20 to 200")
    pick("clip_seconds", lambda v: isinstance(v, int) and not isinstance(v, bool) and 2 <= v <= 15, "must be a whole number from 2 to 15")
    if "target_seconds" in raw:
        v = raw["target_seconds"]
        if isinstance(v, list) and len(v) == 2 and all(_is_number(x) for x in v) and 0 < v[0] < v[1] <= 600:
            out["target_seconds"] = v
        else:
            problems.append(f"{where}.target_seconds: must be [min, max] seconds with 0 < min < max <= 600")
    if "materials" in raw:
        v = raw["materials"]
        if isinstance(v, list):
            files = [_file(item, root, VIDEO_EXTENSIONS, f"{where}.materials[{i}]", problems, check_files) for i, item in enumerate(v)]
            out["materials"] = [f for f in files if f]
        else:
            problems.append(f"{where}.materials: must be a list of file paths")
    if "audio_file" in raw:
        v = raw["audio_file"]
        out["audio_file"] = None if v is None else _file(v, root, AUDIO_EXTENSIONS, f"{where}.audio_file", problems, check_files)
    return out


def _terms(value, where: str, problems: list[str], limit: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > limit:
        problems.append(f"{where}: must be a list of at most {limit} search terms")
        return ()
    out = []
    for i, term in enumerate(value):
        if not isinstance(term, str) or not 1 <= len(term.strip()) <= 40 or "," in term or CONTROL.search(term):
            problems.append(f"{where}[{i}]: must be 1 to 40 characters, without a comma")
        else:
            out.append(term.strip())
    return tuple(out)


def _scenes(value, where: str, problems: list[str], warnings: list[str]) -> tuple[Scene, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SCENES:
        problems.append(f"{where}: must be a list of 1 to {MAX_SCENES} scenes")
        return ()
    scenes, total = [], 0
    for i, item in enumerate(value):
        at = f"{where}[{i}]"
        if not isinstance(item, dict):
            problems.append(f"{at}: must be an object with narration and terms")
            continue
        _unknown(item, ("narration", "terms"), at, problems)
        text = item.get("narration")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{at}.narration: must be the words read aloud in this scene")
            continue
        text = " ".join(text.split())
        total += len(text)
        if len(text) > MAX_SCENE_CHARS:
            problems.append(f"{at}.narration: {len(text)} characters; split it, the limit is {MAX_SCENE_CHARS}")
        if CONTROL.search(text):
            problems.append(f"{at}.narration: contains control characters")
        if URL.search(text):
            warnings.append(f"{at}.narration: contains a web address or e-mail; a voice reads it out letter by letter")
        if MARKDOWN.search(text) or EMOJI.search(text):
            warnings.append(f"{at}.narration: contains markup or emoji; the voice reads or skips them and subtitles show them")
        scenes.append(Scene(text, _terms(item.get("terms"), f"{at}.terms", problems, MAX_TERMS_PER_SCENE)))
    if total > MAX_SCRIPT_CHARS:
        problems.append(f"{where}: {total} characters of narration; the limit is {MAX_SCRIPT_CHARS}")
    return tuple(scenes)


def _video(raw, index: int, defaults: dict, root: Path, problems: list[str], warnings: list[str], check_files: bool) -> Job | None:
    where = f"videos[{index}]"
    if not isinstance(raw, dict):
        problems.append(f"{where}: must be an object")
        return None
    vid = raw.get("id")
    if isinstance(vid, str) and SLUG.match(vid):
        where = f"videos[{index}] ({vid})"
    else:
        problems.append(f"{where}.id: must be lowercase letters, digits and hyphens (up to 63), such as 01-first-video")
        vid = None
    _unknown(raw, VIDEO_KEYS, where, problems)
    title = raw.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        problems.append(f"{where}.title: must be 1 to 120 characters")
        title = ""
    scenes = _scenes(raw.get("scenes"), f"{where}.scenes", problems, warnings)
    extra = _terms(raw.get("terms"), f"{where}.terms", problems, 40)

    own = _settings({k: v for k, v in raw.items() if k in SETTINGS}, root, where, problems, check_files)
    cfg = {**BUILT_IN, **defaults, **own}
    language, voice, source = cfg["language"], cfg["voice"], cfg["material_source"]

    if cfg["audio_file"] is None and voice != NO_VOICE and "Multilingual" not in voice and voice.split("-")[0] != language.split("-")[0]:
        problems.append(f"{where}.voice: {voice} reads {voice.split('-')[0]}, but the language is {language}")
    if source == "local" and not cfg["materials"]:
        problems.append(f"{where}.materials: material_source is local, so list the video or image files to use")
    if source != "local" and cfg["materials"]:
        problems.append(f"{where}.materials: only valid when material_source is local")
    if source != "local" and not scenes_have_terms(scenes, extra):
        problems.append(f"{where}: give search terms (scene terms or terms); without them MPT would ask an LLM for them")
    if cfg["audio_file"] and cfg["subtitles"]:
        warnings.append(f"{where}: audio_file with subtitles needs subtitle_provider = \"whisper\" in MPT's config.toml, or no subtitles are made")
    if cfg["bgm"] not in ("none", "random") and not MUSIC_NAME.fullmatch(cfg["bgm"]):
        problems.append(f"{where}.bgm: must be none, random or a music file name")

    if vid is None or not scenes:
        return None
    lo, hi = cfg["target_seconds"]
    font = cfg["font"] or FONT_BY_LANGUAGE.get(language.split("-")[0], FONT_DEFAULT)
    job = Job(
        id=vid, title=title.strip(), scenes=scenes, extra_terms=extra, language=language, aspect=cfg["aspect"], voice=voice,
        voice_rate=float(cfg["voice_rate"]), voice_volume=float(cfg["voice_volume"]), material_source=source,
        materials=tuple(cfg["materials"]), audio_file=cfg["audio_file"], bgm=cfg["bgm"], bgm_volume=float(cfg["bgm_volume"]),
        subtitles=cfg["subtitles"], font=font, font_size=cfg["font_size"], clip_seconds=cfg["clip_seconds"],
        min_seconds=float(lo), max_seconds=float(hi),
    )
    if cfg["audio_file"] is None and not lo * 0.7 <= job.estimate_seconds() <= hi * 1.3:
        warnings.append(f"{where}: reads for about {job.estimate_seconds():g} s, but target_seconds is [{lo:g}, {hi:g}]")
    return job


def scenes_have_terms(scenes: tuple[Scene, ...], extra: tuple[str, ...]) -> bool:
    return bool(extra) or any(scene.terms for scene in scenes)


def load_pack(path: str | Path, *, check_files: bool = True) -> Pack:
    """Read a pack (a JSON file or a directory) and return its jobs, or raise PackError listing every problem."""
    path = Path(path)
    problems: list[str] = []
    warnings: list[str] = []
    if path.is_dir():
        root, head_file = path, path / "pack.json"
        head = _read_json(head_file, problems) if head_file.is_file() else None
        if not head_file.is_file():
            problems.append(f"{head_file}: missing (a pack directory needs pack.json with batch and defaults)")
        videos_dir = path / "videos"
        files = sorted(videos_dir.glob("*.json")) if videos_dir.is_dir() else []
        if not files:
            problems.append(f"{videos_dir}: no *.json files (one video each)")
        videos = []
        for file in files:
            item = _read_json(file, problems)
            if isinstance(item, dict) and item.get("id") not in (None, file.stem):
                problems.append(f"{file}: the file name must be <id>.json, and the id is {item.get('id')!r}")
            videos.append(item)
        allowed = DIR_TOP_KEYS
    elif path.is_file():
        root = path.parent
        head = _read_json(path, problems)
        videos = head.get("videos") if isinstance(head, dict) else None
        allowed = TOP_KEYS
    else:
        raise PackError([f"{path}: no such file or directory"])

    if not isinstance(head, dict):
        problems.append(f"{path}: the pack must be a JSON object")
        raise PackError(problems)
    _unknown(head, allowed, "pack", problems)
    if head.get("version", 1) != 1:
        problems.append("pack.version: only version 1 is known")
    batch = head.get("batch")
    if not (isinstance(batch, str) and SLUG.match(batch)):
        problems.append("pack.batch: must be lowercase letters, digits and hyphens, such as ai-tips-week-42")
        batch = ""
    raw_defaults = head.get("defaults", {})
    if not isinstance(raw_defaults, dict):
        problems.append("pack.defaults: must be an object")
        raw_defaults = {}
    _unknown(raw_defaults, SETTINGS, "pack.defaults", problems)
    defaults = _settings({k: v for k, v in raw_defaults.items() if k in SETTINGS}, root, "pack.defaults", problems, check_files)

    jobs: list[Job] = []
    if not isinstance(videos, list) or not videos:
        problems.append("pack.videos: must be a non-empty list")
    elif len(videos) > MAX_VIDEOS:
        problems.append(f"pack.videos: {len(videos)} videos; the limit is {MAX_VIDEOS}")
    else:
        for index, raw in enumerate(videos):
            job = _video(raw, index, defaults, root, problems, warnings, check_files)
            if job:
                jobs.append(job)
        ids = [job.id for job in jobs]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"pack.videos: id {dup!r} is used more than once")
    if problems:
        raise PackError(problems)
    return Pack(batch=batch, jobs=jobs, warnings=warnings, root=root)
