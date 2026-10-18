"""Turn a GitHub Radar digest (draft-vi.json) into a narrated HyperFrames video project, step by step or all at once.

  plan      DIGEST            what the video would contain and how long the narration is (writes nothing)
  scaffold  DIGEST            create videos/<name>/: the digest as source/, voiceover.json, index.html, music bed
  voice     PROJECT           synthesize every line, pick the best take per line by round trip, fix the timing, run the facts gate
  render    PROJECT           set the audio levels, run `npm run check`, render the MP4, measure it, write README.md and preview.json
  all       DIGEST            scaffold, voice and render

No model writes anything: the scenes, the narration and the on-screen text are the digest's own fields (scripts/radar/plan.py), and
scripts/vo/check_facts.py checks that every number, name and command traces back to them. Rewording a narration line in voiceover.json
is allowed; run `voice --only vo-N` for the lines you changed and the gate decides whether the new wording is still the digest's.

The voice and render steps need the environments of docs/voiceover-workflow.md: --tts-python (VieNeu-TTS) for `voice`, and
--asr-python (PhoWhisper) to choose between takes and to measure the result; without it the first take is used and nothing is measured.

usage:
  python3 -I scripts/radar/make_video.py plan /path/to/digests/2026-10-13/voicestudio/draft-vi.json
  python3 -I scripts/radar/make_video.py all  /path/to/draft-vi.json --tts-python .venv/tts/bin/python --asr-python .venv/asr/bin/python
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))  # the modules next to this file; -I does not add the script's folder
sys.path.insert(0, str(REPO / "scripts" / "vo"))  # numbers_vi, shared with check_facts.py

import compose  # noqa: E402
import plan as planlib  # noqa: E402
from numbers_vi import speak_text  # noqa: E402
from line_ids import duplicate_line_ids  # noqa: E402

DEFAULT_VOICE = "Hải Đăng"          # the same default as scripts/vo/synth.py
HYPERFRAMES_VERSION = "0.8.168"   # pinned into each project's package.json by `hyperframes init`
VO = REPO / "scripts" / "vo"
TAKE_WORRY = 0.30                  # a chosen take with more than this share of wrong words is flagged in the report


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def clip_seconds(path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], check=True).stdout
    return float(out.strip())


def whole_file_levels(path):
    err = run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"]).stderr
    mean, peak = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err), re.search(r"max_volume:\s*(-?[\d.]+) dB", err)
    return (float(mean.group(1)), float(peak.group(1))) if mean and peak else (None, None)


def clip_durations(project: Path, doc) -> dict:
    """Length of each line's clip in assets/; a missing clip stops the command with its name."""
    missing = [line["id"] for line in doc["lines"] if not (project / "assets" / f"{line['id']}.wav").is_file()]
    if missing:
        fail(f"no clip in assets/ for {', '.join(missing)}; run `voice {rel(project)}` first")
    return {line["id"]: clip_seconds(project / "assets" / f"{line['id']}.wav") for line in doc["lines"]}


CLIP_VOLUME = re.compile(r'(<audio id="vo-[^"]*"[^>]*?) data-volume="[^"]*"')


def expected_page(project: Path) -> str:
    """The index.html that compose.py writes for this project: the digest in source/, the lines of voiceover.json, the clips in assets/."""
    digest, plan, doc = load_project(project)
    return compose.render(plan, planlib.timeline(plan, clip_durations(project, doc)))


def require_generated_page(project: Path):
    """index.html of a generated project is what compose.py writes, except the data-volume of the voice clips (revoice.py sets those).
    The facts gate reads the page's text and a list of what its code may contain; this closes what a list cannot: an edit that uses
    only what the template itself uses (a GSAP call that fades out a command row, a moved start time)."""
    mask = lambda html: CLIP_VOLUME.sub(r'\1 data-volume="V"', html)
    actual, expected = mask((project / "index.html").read_text(encoding="utf-8")), mask(expected_page(project))
    if actual != expected:
        lines = zip(actual.splitlines() + [""] * len(expected.splitlines()), expected.splitlines() + [""] * len(actual.splitlines()))
        first = next(((n, a, e) for n, (a, e) in enumerate(lines, 1) if a != e), (0, "", ""))
        fail(f"index.html is not what compose.py writes for this project (first difference at line {first[0]}: "
             f"{first[1].strip()[:90]!r} instead of {first[2].strip()[:90]!r}). A change to the page belongs in compose.py; "
             f"`make_video.py rebuild {rel(project)}` writes the page again from the digest and the clips")


TIMING_FIELDS = ("id", "unit", "start", "scene_end", "scene")


def require_generated_timing(project: Path):
    """The lines of voiceover.json say when each clip starts, and revoice.py writes those times into the page it renders. The page was
    just checked against compose.py, which uses the timeline made from the clips; the times in voiceover.json have to be that timeline
    too, or two sentences could play in the wrong order under a page that passed. The words may be reworded by hand; the timing may not."""
    digest, plan, doc = load_project(project)
    expected = voiceover_doc(plan, planlib.timeline(plan, clip_durations(project, doc)), doc)["lines"]
    if [line["id"] for line in expected] != [line.get("id") for line in doc["lines"]]:
        fail(f"the lines of voiceover.json are not the lines of the plan; `make_video.py rebuild {rel(project)}` writes them again")
    wrong = [have["id"] for want, have in zip(expected, doc["lines"]) if any(have.get(field) != want[field] for field in TIMING_FIELDS)]
    if wrong:
        fail(f"the timing of {', '.join(wrong)} in voiceover.json (start, scene_end, scene) is not what the clips give, and revoice.py would "
             f"write it into the page: `make_video.py rebuild {rel(project)}` writes it again")


SCAFFOLD_FILES = ("package.json", "hyperframes.json")   # what `hyperframes init` writes and render runs through npm; scaffold records their hashes


def expected_scripts() -> dict:
    """The scripts `hyperframes init` puts in package.json, at the version scaffold pins: the only commands `npm run check` and `npm run render` run."""
    pinned = f"npx --yes hyperframes@{HYPERFRAMES_VERSION}"
    return {"dev": f"{pinned} preview", "check": f"{pinned} check", "render": f"{pinned} render", "publish": f"{pinned} publish"}


def file_sha256(path: Path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def require_scaffold_files(project: Path):
    """render hands the project to revoice.py, which runs `npm run check` and `npm run render`: npm runs whatever the scripts of package.json
    say (`npm run` is "run arbitrary package scripts"), and its hooks (prerender, postrender, precheck ...) and the project's .npmrc (a
    script-shell, node options) as well. The checks before this one cover the digest, the page, the timing and the clips, none of which a
    script that renders another page, or runs any command at all, has to respect. So the render goes through the files scaffold wrote:
    package.json is exactly the scaffold's (the four pinned commands, no hook, no other key), hyperframes.json is the one whose hash
    scaffold recorded in source/provenance.json, and there is no .npmrc."""
    try:
        package = json.loads((project / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        package = None
    problems = []
    if not (isinstance(package, dict) and set(package) == {"name", "private", "type", "scripts"} and isinstance(package["name"], str)
            and package["private"] is True and package["type"] == "module" and package["scripts"] == expected_scripts()):
        problems.append("package.json is not the one scaffold wrote (its scripts are the commands npm runs; they have to be the four pinned `npx hyperframes` "
                        "ones, with no hook and no other key)")
    try:
        recorded = json.loads((project / "source" / "provenance.json").read_text(encoding="utf-8")).get("scaffold_files")
    except (OSError, ValueError, AttributeError):
        recorded = None
    if not isinstance(recorded, dict) or recorded.get("hyperframes.json") is None or recorded.get("hyperframes.json") != file_sha256(project / "hyperframes.json"):
        problems.append("hyperframes.json is not the one scaffold recorded (source/provenance.json `scaffold_files`)")
    if (project / ".npmrc").exists():
        problems.append("there is a .npmrc in the project, which changes how npm runs the scripts")
    if problems:
        fail("; ".join(problems) + f". Render only runs what scaffold wrote: scaffold the project again from the digest ({rel(project)})")


AUDIBLE_DB = -45.0     # a mean volume below this is a render with no narration in it (the voice sits near -20 dB)


def require_audible(mean, peak):
    """A radar video is narrated: an MP4 with no audio stream (None), silence (-inf, -91 dB ...) or only a whisper is a failed render."""
    if mean is None or peak is None or mean < AUDIBLE_DB:
        fail(f"the rendered MP4 has no audible sound (mean {mean} dB, peak {peak} dB; the narration is missing or silent). "
             f"Check assets/*.wav and the audio of index.html, then render again")


VIDEO_SIZE, VIDEO_FPS = (1920, 1080), 30     # what compose.py draws, and what the README and the preview page say of the render
LENGTH_SLACK = 0.5                            # seconds the MP4 may differ from the planned timeline (a frame is 0.033)


def video_problems(path, planned_seconds: float) -> list:
    """What differs between the MP4 and the video the project describes: no video stream, another size or frame rate, or a length that is
    not the planned timeline's (a render that stopped early, or an older file left in renders/). The length is the video stream's own: the
    container is as long as its longest stream, so narration that runs to the end hides a picture that stopped short. The README and the
    preview page state the size, the frame rate and the length, so they are measured here, not assumed from what the page asks for."""
    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate,duration", "-of", "json", path])
    try:
        data = json.loads(probe.stdout or "{}")
        streams = data["streams"]
    except (ValueError, KeyError, TypeError):
        return ["the file has no readable video stream or length"]
    if not streams:
        return ["the file has no video stream"]
    stream = streams[0]
    try:
        seconds = float(stream["duration"])          # the picture's own length, not the container's: sound that runs on keeps the container long
    except (ValueError, KeyError, TypeError):
        return ["the video stream has no readable length"]
    problems = []
    size = (stream.get("width"), stream.get("height"))
    if size != VIDEO_SIZE:
        problems.append(f"the picture is {size[0]}×{size[1]}, not {VIDEO_SIZE[0]}×{VIDEO_SIZE[1]}")
    numerator, _, denominator = str(stream.get("avg_frame_rate", "")).partition("/")
    try:
        fps = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if abs(fps - VIDEO_FPS) > 0.01:
        problems.append(f"the frame rate is {fps:g}, not {VIDEO_FPS}")
    if abs(seconds - planned_seconds) > LENGTH_SLACK:
        problems.append(f"the picture is {seconds:.2f} s long, the timeline {planned_seconds:.2f} s")
    return problems


def require_planned_video(path, planned_seconds: float):
    problems = video_problems(path, planned_seconds)
    if problems:
        fail("the rendered MP4 is not the video the project describes: " + "; ".join(problems) + ". Render again (an older or partial file in renders/ "
             "is not kept)")


NARRATION_OVER_MUSIC_DB = 6.0    # a clip's stretch of the MP4 has to be this much louder than the music bed alone


def segment_mean(path, start: float, seconds: float):
    """Mean volume (dB) of `seconds` of the audio of `path` from `start`, or None when there is no audio there."""
    err = run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", path, "-vn", "-af", "volumedetect",
               "-f", "null", "-"]).stderr
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    return float(mean.group(1)) if mean else None


def music_bed_db(project: Path) -> float:
    """How loud the music bed is in the render: its own mean level plus its data-volume in index.html (0.6 if the page says nothing)."""
    mean = segment_mean(project / "assets" / "pad.wav", 0.0, clip_seconds(project / "assets" / "pad.wav"))
    volume = re.search(r'id="music-bed"[^>]*data-volume="([\d.]+)"', (project / "index.html").read_text(encoding="utf-8"))
    factor = float(volume.group(1)) if volume else 0.6
    return (mean if mean is not None else -91.0) + 20 * math.log10(factor) if factor > 0 else -91.0


def silent_narration(project: Path, doc, mp4) -> list:
    """Ids of the lines whose stretch of the render is no louder than the music bed alone: the whole mix can clear the audible level on
    music only (the bed sits near -34 dB), so each clip's own seconds are measured."""
    floor = music_bed_db(project) + NARRATION_OVER_MUSIC_DB
    missing = []
    for line in doc["lines"]:
        wav = project / "assets" / f"{line['id']}.wav"
        mean = segment_mean(mp4, line["start"], clip_seconds(wav))
        if mean is None or mean < floor:
            missing.append(line["id"])
    return missing


def make_pad(path: Path, seconds: float):
    """A quiet chord of four sines, lowpassed: the music bed. Mono 16 kHz is enough below 900 Hz and keeps the file small."""
    d = f"{seconds:.2f}"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for freq in (110, 164.81, 220, 277.18):
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:duration={d}"]
    fade_out_at = max(0.0, seconds - 2.5)
    cmd += ["-filter_complex",
            "[0]volume=0.5[a];[1]volume=0.35[b];[2]volume=0.3[c];[3]volume=0.15,tremolo=f=0.35:d=0.6[d];"
            f"[a][b][c][d]amix=inputs=4:normalize=0,lowpass=f=900,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_at:.2f}:d=2.5,volume=0.55",
            "-ac", "1", "-ar", "16000", path]
    result = run(cmd)
    if result.returncode:
        fail(f"ffmpeg could not make the music bed: {result.stderr[-400:]}")


def refresh_music_bed(project: Path, plan, doc):
    """assets/pad.wav is made by make_pad from the length of the video, and nothing else: the facts gate does not listen, the clips are
    fingerprinted but the bed is not a clip, and the level check after a render compares the bed with itself. A render therefore writes it
    again, so that a file put there (another music, a voice, something without a licence) never reaches the MP4."""
    make_pad(project / "assets" / "pad.wav", planlib.timeline(plan, clip_durations(project, doc))["duration"])


def without_credentials(url):
    """A git remote as a public address, for provenance.json and README.md (both committed): scheme://host/path, or host:path for the
    scp style. The user name or password (user:pw@, token@), the query and the fragment are dropped, because a token can sit in any of
    them."""
    if not url:
        return url
    if re.match(r"[A-Za-z][A-Za-z0-9+.\-]*://", url):
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}"
    scp = re.match(r"(?:[^@/:\s]+@)?([^@/:\s]+):(.*)", url)          # [user@]host:path
    if scp:
        return f"{scp.group(1)}:{re.split(r'[?#]', scp.group(2))[0]}"
    return re.split(r"[?#]", url)[0]


def where_it_came_from(path: Path) -> dict:
    """The digest's place in its git repository (remote, path, last commit), or just its file name when it is not in one."""
    top = run(["git", "-C", path.parent, "rev-parse", "--show-toplevel"])
    if top.returncode:
        return {"file": path.name}
    remote = without_credentials(run(["git", "-C", path.parent, "remote", "get-url", "origin"]).stdout.strip() or None)
    last = run(["git", "-C", path.parent, "log", "-1", "--format=%H %cs", "--", path.name]).stdout.strip() or None
    return {"git_remote": remote, "path_in_repo": str(path.relative_to(Path(top.stdout.strip()).resolve())), "last_commit_of_file": last}


def project_dir(arg, videos_dir) -> Path:
    path = Path(arg)
    if path.is_dir():
        return path.resolve()
    candidate = Path(videos_dir) / arg
    if candidate.is_dir():
        return candidate.resolve()
    fail(f"no such project: {arg}")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def voiceover_doc(plan, tl, existing=None) -> dict:
    """voiceover.json: one line per unit. Wording a person changed in `existing` (text, speak) is kept."""
    old = {l["unit"]: l for l in (existing or {}).get("lines", []) if "unit" in l}
    lines = []
    scene_of = {uid: s for s in tl["scenes"] for uid in next(sc["units"] for sc in plan["scenes"] if sc["id"] == s["id"])}
    for unit in plan["units"]:
        clip, scene = tl["clips"][unit["id"]], scene_of[unit["id"]]
        line = {"id": unit["id"], "unit": unit["key"], "start": clip["start"], "scene_end": scene["end"],
                "scene": planlib.unit_label(plan, unit), "text": unit["text"]}
        if unit["key"] in old and old[unit["key"]].get("text") != unit["text"]:     # reworded by hand
            line["text"] = old[unit["key"]]["text"]
            line["source"] = old[unit["key"]].get("source", unit["source"])
        else:
            line["source"] = unit["source"]
        spoken = speak_text(line["text"])
        if spoken != line["text"]:
            line["speak"] = spoken
        if unit["key"] in old and old[unit["key"]].get("voiced"):
            line["voiced"] = old[unit["key"]]["voiced"]          # which words the clip in assets/ was made from
            if old[unit["key"]].get("clip"):
                line["clip"] = old[unit["key"]]["clip"]          # and which clip that was
            if old[unit["key"]].get("voice"):
                line["voice"] = old[unit["key"]]["voice"]        # and who read it
        lines.append(line)
    doc = {"allow": (existing or {}).get("allow", [])}
    if (existing or {}).get("voice"):
        doc["voice"] = existing["voice"]                        # the narrator of the clips in assets/
    if plan["try"] and plan["try"]["commands"]:
        doc["commands_shown"] = len(plan["try"]["commands"])    # the terminal's commands the gate must find on screen, exactly
    doc["lines"] = lines
    return doc


def voiced_fingerprint(text) -> str:
    """A short hash of what the synthesizer is given for a line. A clip in assets/ is good for the words it was made from: `voice`
    records this per line, and `render` refuses a line whose words have changed since."""
    return hashlib.sha1(speak_text(text).encode("utf-8")).hexdigest()[:12]


def clip_fingerprint(wav: Path) -> str:
    """A short hash of a clip's bytes, or "" for a clip that is not there. `voice` records it per line beside the words: the words do
    not tell which file was made from them, and a clip swapped for another line's would say the wrong sentence under the right text."""
    return hashlib.sha256(wav.read_bytes()).hexdigest()[:16] if wav.is_file() else ""


def stale_voices(doc, assets: Path) -> list:
    """Ids of the lines whose clip in `assets` is not the one `voice` made from their current words: reworded and not voiced again,
    never voiced, or the file is not the one that was recorded (replaced or missing)."""
    return [line["id"] for line in doc["lines"]
            if line.get("voiced") != voiced_fingerprint(line["text"])
            or not line.get("clip") or line["clip"] != clip_fingerprint(assets / f"{line['id']}.wav")
            or not line.get("voice") or line["voice"] != doc.get("voice")]


def require_one_narrator(doc, redone, voice_name):
    """A video has one narrator. `voice` records on each line who read its clip; a run that redoes only some lines with a voice other than
    the one the other clips were made with (or with no record of it) would mix two narrators, whatever the project file now says."""
    kept = [line for line in doc["lines"] if line["id"] not in redone]
    others = sorted({line.get("voice") or "an unknown voice" for line in kept if line.get("voice") != voice_name})
    if others:
        fail(f"the other clips of this video were read by {', '.join(others)}, not by {voice_name}: --only would mix two voices. "
             f"Redo every line (no --only) to change the voice, or keep the voice of the other clips")


def refresh_speak(doc) -> bool:
    """Make every line's `speak` the spelled-out form of its current `text` before synthesizing. `speak` is derived, never written
    by hand: scripts/vo/check_facts.py refuses a line whose `speak` is anything else, because `speak` is what the viewer hears.
    Returns True when something changed."""
    changed = False
    for line in doc["lines"]:
        spoken = speak_text(line["text"])
        wanted = spoken if spoken != line["text"] else None
        if wanted != line.get("speak"):
            changed = True
            if wanted:
                line["speak"] = wanted
            else:
                line.pop("speak", None)
    return changed


def write_json(path: Path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_source_unchanged(project: Path):
    """source/draft-vi.json is the digest `scaffold` copied, byte for byte, and source/provenance.json records its sha256. Everything in the
    project (the plan, the page the gate compares with, the facts the words are traced to) is derived from that file, so a file that was
    edited afterwards would make a changed number pass every check and still be called a verbatim copy. A project whose record is
    missing or does not match is not rebuilt, voiced or rendered; scaffold it again from the digest."""
    source = project / "source"
    try:
        recorded = json.loads((source / "provenance.json").read_text(encoding="utf-8")).get("sha256")
        actual = hashlib.sha256((source / "draft-vi.json").read_bytes()).hexdigest()
    except (OSError, ValueError, AttributeError):
        recorded = actual = None
    if not recorded or recorded != actual:
        fail(f"{rel(source / 'draft-vi.json')} is not the digest that scaffold copied (its sha256 is not the one in source/provenance.json, "
             f"or there is no record): every word and number of the video is traced to this file, so it must stay as it was. Scaffold the "
             f"project again from the digest")


def require_chosen_lines(project: Path, selection):
    """The lines of voiceover.json are the ones `scaffold` chose within the speech budget (source/provenance.json records their keys).
    The plan is made from voiceover.json's own list, so a list emptied or cut down by hand would still be self-consistent: a video with
    no narration at all would pass every check and render as music over a terminal. Lines are not added or dropped by hand; scaffold
    again (--speech-seconds for a shorter or longer video)."""
    try:
        chosen = json.loads((project / "source" / "provenance.json").read_text(encoding="utf-8")).get("units")
    except (OSError, ValueError, AttributeError):
        chosen = None
    if not isinstance(chosen, list) or not chosen or chosen != list(selection):
        fail(f"voiceover.json lists {len(selection)} line(s), not the {len(chosen) if isinstance(chosen, list) else 'recorded'} that scaffold chose "
             f"(source/provenance.json `units`, in this order): a line cannot be added, dropped or moved by hand. Scaffold the project again "
             f"from the digest, with --speech-seconds for a shorter or longer video")


LINE_ID = re.compile(r"vo-[1-9]\d*")      # what plan.py names a unit; also the file name of its clip, assets/<id>.wav


def require_line_ids(doc):
    """A line id is a file name: synth.py writes <id>.wav, voice copies it into assets/, render reads it. An id with a slash, `..` or a
    drive in it (`/tmp/target`, `../../x`) would write or read a file outside the project, and this runs before the facts gate does.
    scaffold writes vo-1, vo-2 ...; nothing else is a line of a generated project."""
    bad = [line.get("id") if isinstance(line, dict) else line for line in doc.get("lines") or []
           if not isinstance(line, dict) or not isinstance(line.get("id"), str) or not LINE_ID.fullmatch(line["id"])]
    if bad:
        fail(f"voiceover.json has a line id that is not vo-N ({bad[:3]!r}): an id is the name of the line's clip file, and scaffold is the "
             f"only thing that writes one. Scaffold the project again from the digest")
    repeated = duplicate_line_ids(doc.get("lines") or [])
    if repeated:
        fail(f"voiceover.json has two lines with the id {", ".join(map(repr, repeated[:3]))}: they would share one clip file and only the later would be heard. "
             f"Scaffold the project again from the digest")


def load_project(project: Path):
    """(digest, plan, voiceover doc) rebuilt from source/ and voiceover.json."""
    require_source_unchanged(project)
    digest = planlib.load_digest(project / "source" / "draft-vi.json")
    doc = json.loads((project / "voiceover.json").read_text(encoding="utf-8"))
    require_line_ids(doc)
    selection = [line.get("unit") for line in doc.get("lines") or []]
    require_chosen_lines(project, selection)
    return digest, planlib.build_plan(digest, selection=selection), doc


def write_composition(project: Path, plan, tl, doc=None):
    new_doc = voiceover_doc(plan, tl, doc)
    write_json(project / "voiceover.json", new_doc)
    (project / "index.html").write_text(compose.render(plan, tl), encoding="utf-8")
    return new_doc


def gate(project: Path):
    """Run scripts/vo/check_facts.py; returns (ok, output)."""
    result = run([sys.executable, "-I", VO / "check_facts.py", "--source", project / "source" / "draft-vi.json",
                  "--lines", project / "voiceover.json", "--html", project / "index.html"])
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def require_gate(project: Path) -> str:
    """Run the facts gate and stop the whole command when it fails: nothing that does not trace to the digest is rendered."""
    ok, output = gate(project)
    if not ok:
        print(output, file=sys.stderr)
        fail("the facts gate failed: voiceover.json or index.html says something the digest does not; fix it, then run this again")
    return output


BUILD = REPO / "build"   # gitignored


def build_dir(project: Path) -> Path:
    """Where a project's takes, report and preview live: its name plus a short hash of its full path, so that two projects with the
    same name in different folders (or a project moved elsewhere) never write into each other's files."""
    return BUILD / f"{project.name}-{hashlib.sha1(str(project.resolve()).encode()).hexdigest()[:8]}"


def reset_build(project: Path):
    """A new project starts with nothing from an earlier project in the same place."""
    shutil.rmtree(build_dir(project), ignore_errors=True)


def report_path(project: Path) -> Path:
    return build_dir(project) / "report.json"


def load_report(project: Path) -> dict:
    path = report_path(project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_report(project: Path, report: dict):
    path = report_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, report)


# ----------------------------------------------------------------------------------------------------------------- scaffold
def cmd_plan(args):
    digest = planlib.load_digest(args.digest)
    print(planlib.format_plan(planlib.build_plan(digest, speech_seconds=args.speech_seconds)))


def scaffold_readme(plan) -> str:
    """The README a scaffolded project has until `render` writes the real one. The repository name is the digest's, so it goes through
    md_text like every other value of a README that comes from the digest."""
    return (f"# Video thử: {md_text(plan['name'])} (từ bài GitHub Radar)\n\nMới tạo khung (scaffold), chưa có giọng đọc và chưa render. "
            f"Nguồn: `source/draft-vi.json`. Chạy `scripts/radar/make_video.py voice` rồi `render`: xem `docs/radar-to-video.md`.\n")


def cmd_scaffold(args) -> Path:
    digest = planlib.load_digest(args.digest)
    plan = planlib.build_plan(digest, speech_seconds=args.speech_seconds)
    name = args.name or re.sub(r"[^a-z0-9]+", "-", plan["name"].lower()).strip("-")
    videos_dir = Path(args.videos_dir)
    project = videos_dir / name
    if project.exists():
        fail(f"{project} already exists; pick another --name (nothing is overwritten)")
    videos_dir.mkdir(parents=True, exist_ok=True)
    reset_build(project)
    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1"}
    init = run(["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "init", name, "--example", "blank", "--non-interactive"],
               cwd=videos_dir, env=env)
    if init.returncode or not (project / "hyperframes.json").exists():
        fail("hyperframes init failed:\n" + strip_ansi(init.stdout + init.stderr)[-1500:])

    source = project / "source"
    source.mkdir()
    shutil.copyfile(args.digest, source / "draft-vi.json")
    digest_path = Path(args.digest).resolve()
    provenance = {
        **where_it_came_from(digest_path),
        "sha256": hashlib.sha256(digest_path.read_bytes()).hexdigest(),
        "units": [unit["key"] for unit in plan["units"]],            # the lines the budget chose: voiceover.json may not add or drop one
        "repo": digest["facts"]["full_name"],
        "scanned": digest["facts"].get("scanned"),
        "scaffold_files": {name: file_sha256(project / name) for name in SCAFFOLD_FILES},       # what render may run through npm
        "generated_by": "scripts/radar/make_video.py scaffold",
    }
    write_json(source / "provenance.json", provenance)
    shutil.copyfile(HERE / "assets" / "gsap.min.js", project / "gsap.min.js")
    (project / "assets").mkdir(exist_ok=True)

    tl = planlib.timeline(plan, {u["id"]: u["est"] for u in plan["units"]})
    write_composition(project, plan, tl)
    make_pad(project / "assets" / "pad.wav", tl["duration"])
    (project / "README.md").write_text(scaffold_readme(plan), encoding="utf-8")

    print(planlib.format_plan(plan))
    print(f"\nscaffolded {rel(project)} (estimated video length {tl['duration']:.0f} s; the real length follows the voice)")
    ok, output = gate(project)
    print("facts gate on the draft:", output.splitlines()[-1] if output else ("ok" if ok else "failed"))
    if not ok:      # `all` goes on to the voice (slow) and `scaffold` is read by a script as done: neither may follow a draft the gate refuses
        print(output, file=sys.stderr)
        fail(f"the facts gate refuses what scaffold wrote from this digest, so {rel(project)} cannot be voiced or rendered. It was left in place to read: "
             f"fix the digest and scaffold again under another --name (nothing is overwritten)")
    return project


# ----------------------------------------------------------------------------------------------------------------- voice
def resolve_voice(requested, doc, report, redoing_some_lines) -> str:
    """The narrator for this run. A project keeps one voice: `voice` in voiceover.json (else the report's), else the default.
    Redoing only some lines with another voice would mix two narrators in one video, so that is refused."""
    recorded = doc.get("voice") or report.get("voice", {}).get("voice")
    if requested and recorded and requested != recorded and redoing_some_lines:
        fail(f"this video is narrated by {recorded}; --only with --voice {requested!r} would mix two voices. "
             f"Redo every line (no --only) to change the voice, or drop --voice to keep {recorded}")
    return requested or recorded or DEFAULT_VOICE


def record_voice(report: dict, voice_name: str, takes: int, asr: bool, chosen: dict) -> dict:
    """Write this run's voice, take count and chosen takes into the report, whatever the report already holds (a render may have
    created `voice` with only the narrator's name)."""
    voice = report.setdefault("voice", {})
    voice.setdefault("chosen", {})
    voice["voice"], voice["takes"], voice["asr"] = voice_name, takes, asr
    for line_id, best in chosen.items():
        share = (best["edits"] / best["ref_words"]) if best["edits"] is not None and best["ref_words"] else None
        voice["chosen"][line_id] = {**best, "wer": None if share is None else round(share, 3),
                                    "flagged": bool(share is not None and share > TAKE_WORRY)}
    return voice


def tool_env(base_env, hf_home):
    env = dict(base_env)
    if hf_home:
        env["HF_HOME"] = str(Path(hf_home).resolve())
        env["HF_HUB_OFFLINE"] = "1"
    return env


def cmd_rebuild(args, project=None):
    """Write index.html, voiceover.json and the music bed again from source/, the lines and the clips in assets/ (no model, no network)."""
    project = project or project_dir(args.project, args.videos_dir)
    digest, plan, doc = load_project(project)
    tl = planlib.timeline(plan, clip_durations(project, doc))
    page = project / "index.html"
    levels = dict(re.findall(r'<audio id="(vo-[^"]*)"[^>]*? data-volume="([^"]*)"', page.read_text(encoding="utf-8"))) if page.is_file() else {}
    write_composition(project, plan, tl, doc)
    make_pad(project / "assets" / "pad.wav", tl["duration"])
    html = page.read_text(encoding="utf-8")
    for clip, level in levels.items():                      # the levels revoice.py set stay; render sets them again anyway
        html = re.sub(rf'(<audio id="{re.escape(clip)}"[^>]*?) data-volume="[^"]*"', rf'\1 data-volume="{level}"', html)
    page.write_text(html, encoding="utf-8")
    print(f"rebuilt {rel(project)}: video length {tl['duration']:.1f} s")


def cmd_voice(args, project=None) -> dict:
    project = project or project_dir(args.project, args.videos_dir)
    if not args.tts_python:
        fail("voice needs --tts-python (the Python of the VieNeu-TTS environment, see docs/voiceover-workflow.md)")
    digest, plan, doc = load_project(project)
    if refresh_speak(doc):
        write_json(project / "voiceover.json", doc)
    ids = [l["id"] for l in doc["lines"]]
    only = [i for i in (args.only.split(",") if args.only else ids)]
    unknown = [i for i in only if i not in ids]
    if unknown:
        fail(f"not a line of voiceover.json: {unknown}")
    voice_name = resolve_voice(args.voice, doc, load_report(project), set(only) != set(ids))
    require_one_narrator(doc, set(only), voice_name)
    doc["voice"] = voice_name
    takes_dir = build_dir(project) / "takes"
    shutil.rmtree(takes_dir, ignore_errors=True)
    tts_env, asr_env = tool_env(os.environ, args.tts_hf_home), tool_env(os.environ, args.asr_hf_home)

    results = {}   # id -> list of {take, edits, ref_words, heard}
    for take in range(1, args.takes + 1):
        out = takes_dir / f"take{take}"
        print(f"take {take}/{args.takes}: synthesizing {len(only)} line(s) ...", flush=True)
        synth = run([args.tts_python, "-I", VO / "synth.py", "--lines", project / "voiceover.json", "--voice", voice_name,
                     "--out", out, "--only", ",".join(only)], env=tts_env)
        if synth.returncode:
            fail("synth.py failed:\n" + synth.stderr[-1500:])
        if args.asr_python:
            check = run([args.asr_python, "-I", VO / "roundtrip.py", "--out", out / "roundtrip.json", out / "manifest.json"], env=asr_env)
            if check.returncode:
                fail("roundtrip.py failed:\n" + check.stderr[-1500:])
            for row in json.loads((out / "roundtrip.json").read_text(encoding="utf-8"))["rows"]:
                results.setdefault(row["id"], []).append({"take": take, "edits": row["edits"], "ref_words": row["ref_words"], "heard": row["heard"]})
        else:
            for line_id in only:
                results.setdefault(line_id, []).append({"take": take, "edits": None, "ref_words": None, "heard": None})

    chosen = {}
    for line_id in only:
        candidates = results[line_id]
        best = min(candidates, key=lambda c: (c["edits"] if c["edits"] is not None else 0, c["take"]))
        chosen[line_id] = best
        shutil.copyfile(takes_dir / f"take{best['take']}" / f"{line_id}.wav", project / "assets" / f"{line_id}.wav")

    durations = {}
    for line_id in ids:
        wav = project / "assets" / f"{line_id}.wav"
        if not wav.exists():
            fail(f"{rel(wav)} is missing; run voice without --only first")
        durations[line_id] = clip_seconds(wav)
    tl = planlib.timeline(plan, durations)
    for line in doc["lines"]:
        if line["id"] in only:
            line["voiced"] = voiced_fingerprint(line["text"])       # the clip just copied to assets/ was made from these words
            line["clip"] = clip_fingerprint(project / "assets" / f"{line['id']}.wav")     # and it is this file
            line["voice"] = voice_name                                                    # read by this narrator
    write_composition(project, plan, tl, doc)
    make_pad(project / "assets" / "pad.wav", tl["duration"])

    report = load_report(project)
    voice = record_voice(report, voice_name, args.takes, bool(args.asr_python), chosen)
    ok, output = gate(project)
    report["gate"] = {"ok": ok, "output": output}
    report["duration"] = tl["duration"]
    save_report(project, report)

    print(f"\nvoice: {len(ids)} lines, video length {tl['duration']:.1f} s")
    for line_id in only:
        c = voice["chosen"][line_id]
        detail = "not measured (no --asr-python)" if c["wer"] is None else f"{c['edits']}/{c['ref_words']} words wrong"
        print(f"  {line_id}: take {c['take']}, {detail}{'  <- FLAGGED: reword the line and run voice --only ' + line_id if c['flagged'] else ''}")
    print("facts gate:", output.splitlines()[-1] if output else "ok")
    if not ok:
        print(output, file=sys.stderr)
        fail("the facts gate failed; fix voiceover.json (or the wording of a line) and run voice --only again")
    return report


# ----------------------------------------------------------------------------------------------------------------- render
def final_mix_wer(args, project: Path, mp4: Path):
    if not args.asr_python:
        return None
    out = build_dir(project) / "final-mix.json"
    result = run([args.asr_python, "-I", VO / "roundtrip.py", "--out", out, "--video", mp4, "--lines", project / "voiceover.json",
                  "--label", "final mix"], env=tool_env(os.environ, args.asr_hf_home))
    if result.returncode:
        fail("roundtrip.py on the MP4 failed:\n" + result.stderr[-1500:])
    data = json.loads(out.read_text(encoding="utf-8"))
    return {"edits": data["summary"][0]["edits"], "ref_words": data["summary"][0]["ref_words"],
            "rows": [{k: r[k] for k in ("id", "edits", "ref_words", "heard")} for r in data["rows"]]}


def cmd_render(args, project=None) -> dict:
    project = project or project_dir(args.project, args.videos_dir)
    digest, plan, doc = load_project(project)
    gate_output = require_gate(project)          # before the slow steps, and a failure ends the command
    require_generated_page(project)
    require_generated_timing(project)
    require_scaffold_files(project)              # before npm runs anything of the project
    refresh_music_bed(project, plan, doc)
    stale = stale_voices(doc, project / "assets")
    if stale:
        fail(f"the clip of {', '.join(stale)} is not the one `voice` made from the line's current words (reworded since, never voiced, "
             f"or the file in assets/ was replaced): run `voice {rel(project)} --only {','.join(stale)}` (or without --only) first, "
             f"so that what is heard is what was checked")
    mp4 = project / "renders" / f"{project.name}.mp4"
    print("render: revoice.py (levels, npm run check, render) ...", flush=True)
    result = run([sys.executable, "-I", VO / "revoice.py", "--project", project, "--lines", project / "voiceover.json",
                  "--clips", project / "assets", "--out", mp4, "--apply"])
    text = strip_ansi(result.stdout + result.stderr)
    if result.returncode:
        fail("revoice.py failed:\n" + text[-2500:])
    check_line = next((l for l in text.splitlines() if l.startswith("check:")), "check: (no summary)")
    warnings = [l.strip() for l in text.splitlines() if "WARNING" in l]
    require_planned_video(mp4, planlib.timeline(plan, clip_durations(project, doc))["duration"])     # before the report says its size, rate and length
    mean, peak = whole_file_levels(mp4)
    require_audible(mean, peak)                  # before the report, README and preview call this render a success
    silent = silent_narration(project, json.loads((project / "voiceover.json").read_text(encoding="utf-8")), mp4)
    if silent:
        fail(f"the render has no narration where {', '.join(silent)} should be heard (only the music bed, or less): the clips of assets/ "
             f"did not reach the MP4. Check the audio elements of index.html, then render again")
    seconds = clip_seconds(mp4)
    final = final_mix_wer(args, project, mp4)

    report = load_report(project)
    if not report.get("voice", {}).get("voice") and doc.get("voice"):     # no report (a fresh checkout): the project still says who narrates
        report.setdefault("voice", {})["voice"] = doc["voice"]
    report["render"] = {"check": check_line.replace("check: ", ""), "duration": round(seconds, 2), "mean_db": mean, "peak_db": peak,
                        "warnings": warnings, "final_mix": final}
    report["gate"] = {"ok": True, "output": gate_output}
    save_report(project, report)
    write_preview_json(project, plan, report)
    write_readme(project, plan, doc, report)
    if args.preview:
        page = build_dir(project) / "preview" / "index.html"
        built = run([sys.executable, "-I", REPO / "scripts" / "preview" / "build_preview.py", "--config", project / "preview.json", "--out", page])
        if built.returncode:
            fail("build_preview.py failed:\n" + (built.stdout + built.stderr)[-1500:])
        print("preview page:", rel(page))

    print(f"\nrendered {rel(mp4)}: {seconds:.1f} s, mean {mean} dB, peak {peak} dB")
    print(check_line)
    for w in warnings:
        print(w)
    if final:
        print(f"final mix round trip: {final['edits']}/{final['ref_words']} words wrong ({100 * final['edits'] / max(final['ref_words'], 1):.0f}%)")
    print("facts gate:", gate_output.splitlines()[-1] if gate_output else "ok")
    return report


def voice_slug(name: str) -> str:
    """hai-dang for "Hải Đăng": what build_preview.py wants in a key."""
    plain = unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in plain if not unicodedata.combining(c)).lower()).strip("-") or "voice"


def write_preview_json(project: Path, plan, report):
    voice = report.get("voice", {}).get("voice", DEFAULT_VOICE)
    render = report.get("render", {})
    final = render.get("final_mix")
    measured = (f"PhoWhisper-small nghe lại âm thanh cắt từ chính file video này, sai {final['edits']} trên {final['ref_words']} từ "
                f"({100 * final['edits'] / max(final['ref_words'], 1):.0f}%). Lỗi chủ yếu ở từ tiếng Anh và tên riêng, vì giọng đọc chúng theo kiểu Việt hóa."
                if final else "Mức dễ hiểu chưa được đo (không có môi trường nhận dạng giọng nói khi dựng).")
    doc = {
        "title": f"Video tự động {plan['name']}",
        "eyebrow": f"Video-AI · từ bài GitHub Radar {plan['scan']}".strip(),
        "lede": (f"Video {render.get('duration', 0):.0f} giây tự động dựng từ một bài radar: lời đọc tiếng Việt giọng {voice} (VieNeu-TTS) và nhạc nền. "
                 "Mọi số, tên và lệnh trên màn hình lấy từ các trường của bài, và một script đã kiểm tra điều đó."),
        "lines": "voiceover.json",
        "facts": [["Độ dài", f"{render.get('duration', 0):.1f} giây".replace(".", ",")], ["Hình ảnh", "1920×1080, 30 khung hình/giây"],
                  ["Lời đọc", f"VieNeu-TTS v3 Turbo, giọng {voice}"], ["Nguồn", f"{plan['full_name']}, bài quét ngày {plan['scan']}"]],
        "voices": [{"key": voice_slug(voice), "label": f"Giọng đọc · {voice}", "mp4": f"renders/{project.name}.mp4"}],
        "notes": ["Mức dễ hiểu đã được kiểm tra bằng máy: " + measured if final else measured,
                  "Chưa có người nghe đánh giá độ tự nhiên và độ dễ hiểu của giọng. Script kiểm tra chỉ bắt số, tên và lệnh bịa; "
                  "câu tiếng Việt viết lại cần người đối chiếu với bài."],
    }
    write_json(project / "preview.json", doc)


MD_ACTIVE = re.compile(r"([\\`*_{}\[\]()<>#!|&~:/@])")


def md_line(value) -> str:
    """A value as one line of plain characters: white space of any kind is one space, and no control character is left."""
    return "".join(c for c in " ".join(str(value).split()) if unicodedata.category(c) != "Cc")


def md_text(value) -> str:
    """Text for the README that Markdown shows as it is. A line of the digest is untrusted: `![x](https://host/pixel)` would load that
    address when the README is viewed, `<!-- ... -->` would hide the words after it, `<img>` and a link would be markup. A backslash
    before each character that Markdown reads (and before | , which would split a table row) makes it a letter on the page; the
    facts gate has checked the words, not that they are free of markup."""
    return MD_ACTIVE.sub(r"\\\1", md_line(value))


def md_code(value) -> str:
    """A value in a code span, which Markdown shows as it is: a fence longer than any run of backticks inside it, so no text closes it early."""
    text = md_line(value)
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def write_readme(project: Path, plan, doc, report):
    base, voice, render = rel(project), report.get("voice", {}), report.get("render", {})
    narrator = md_text(voice.get("voice", DEFAULT_VOICE))
    prov = json.loads((project / "source" / "provenance.json").read_text(encoding="utf-8")) if (project / "source" / "provenance.json").exists() else {}
    rows = []
    for line in doc["lines"]:
        c = voice.get("chosen", {}).get(line["id"], {})
        measured = f"{c['edits']}/{c['ref_words']}" if c.get("edits") is not None else "chưa đo"
        shown = line["text"] if len(line["text"]) <= 150 else line["text"][:147] + "..."
        shown = md_text(shown)      # markup, a pipe or a line break in the text would be markup, or split the table row
        rows.append(f"| {md_code(line['id'])} | {line['start']:g} s | {shown} | {c.get('take', '?')} | {measured}{' (cờ)' if c.get('flagged') else ''} |")
    if prov.get("path_in_repo"):
        origin_text = (f"file {md_code(prov['path_in_repo'])} trong repo {md_code(prov.get('git_remote'))} "
                       f"(bản ghi cuối cùng của file: {md_code(prov.get('last_commit_of_file'))})")
    else:
        origin_text = f"file {md_code(prov.get('file', '?'))}"
    if prov.get("also_via"):
        origin_text += f"; {md_text(prov['also_via'])}"
    final = render.get("final_mix")
    levels = (f"âm thanh cả file trung bình {render['mean_db']} dB, đỉnh {render['peak_db']} dB" if render.get("mean_db") is not None else "chưa đo mức âm")
    errors = (f"PhoWhisper-small nghe lại âm thanh cắt từ MP4: sai {final['edits']}/{final['ref_words']} từ "
              f"({100 * final['edits'] / max(final['ref_words'], 1):.0f}%)" if final else "Mức dễ hiểu chưa được đo")
    text = f"""# Video thử: {md_text(plan['name'])} (tự động từ bài GitHub Radar {md_text(plan['scan'])})

Video {render.get('duration', 0):.1f} giây, 1920×1080, 30 khung hình/giây, {len(plan['scenes'])} cảnh, lời đọc tiếng Việt giọng {narrator} (VieNeu-TTS) và nhạc nền tự tạo.
File này do `scripts/radar/make_video.py` tạo ra; cách làm và giới hạn: `docs/radar-to-video.md`.

## Nguồn

`source/draft-vi.json` là bản sao nguyên văn của {origin_text} (sha256 {md_code(str(prov.get('sha256', '?'))[:16] + '...')}). Repo được viết về: {md_code(plan['full_name'])}. Video không dùng mã, hình hay âm thanh nào của repo đó.
Cảnh, lời đọc và chữ trên màn hình đều lấy từ các trường của bài; mỗi dòng của `voiceover.json` ghi trường nó lấy (`source`).

## Chạy lại

Từ thư mục gốc của repo:

```bash
python3 -I scripts/vo/check_facts.py --source {base}/source/draft-vi.json --lines {base}/voiceover.json --html {base}/index.html
python3 -I scripts/radar/make_video.py render {base} --asr-python <python của môi trường PhoWhisper>
```

File MP4 không được commit (`renders/` bị `.gitignore` chặn). Tổng hợp giọng có yếu tố ngẫu nhiên, nên các clip đã chọn nằm trong `assets/`.
Sửa lời đọc trong `voiceover.json` rồi chạy `make_video.py voice {base} --only vo-N --tts-python ...` cho các dòng đã sửa.

## Lời đọc

| Clip | Bắt đầu | Lời đọc | Lượt chọn | Sai/tổng từ của clip |
|---|---|---|---|---|
{chr(10).join(rows)}

## Đã kiểm tra

- Cổng đối chiếu bài (`check_facts.py`): {md_text(report.get('gate', {}).get('output', '?').splitlines()[-1] if report.get('gate', {}).get('output') else '?')}
- `npm run check`: {md_text(render.get('check', 'chưa chạy'))}
- File MP4: {render.get('duration', '?')} giây; {levels}
- {errors}. Máy nghe lại không thay được người nghe: từ tiếng Anh đọc kiểu Việt hóa có thể vẫn dễ hiểu với người Việt.
{chr(10).join('- ' + md_text(w) for w in render.get('warnings', []))}

## Giới hạn

- Chưa có người nghe và đánh giá độ tự nhiên của giọng, nhất là với từ tiếng Anh.
- `check_facts.py` chỉ kiểm số, tên (chữ Latin) và lệnh; lời đọc mặc định là câu nguyên văn của bài nên không lệch ý, nhưng câu nào đã được viết lại cần người đối chiếu.
- Khổ 16:9, chưa có phụ đề.
"""
    (project / "README.md").write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------------------------------------------------- CLI
def add_common(sub):
    sub.add_argument("--videos-dir", default=str(REPO / "videos"), help="where projects live (default: %(default)s)")


def add_voice_args(sub):
    sub.add_argument("--tts-python", help="python of the VieNeu-TTS environment (needed by voice)")
    sub.add_argument("--asr-python", help="python of the PhoWhisper environment (chooses between takes and measures the result)")
    sub.add_argument("--tts-hf-home", help="HF_HOME of the TTS environment (also sets HF_HUB_OFFLINE=1)")
    sub.add_argument("--asr-hf-home", help="HF_HOME of the ASR environment (also sets HF_HUB_OFFLINE=1)")
    sub.add_argument("--takes", type=int, default=3, help="takes per line (default: %(default)s)")
    sub.add_argument("--voice", help=f"VieNeu-TTS preset voice (default: the voice the project already has, else {DEFAULT_VOICE})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = ap.add_subparsers(dest="command", required=True)

    s = subs.add_parser("plan", help="show what the video would contain")
    s.add_argument("digest")
    s.add_argument("--speech-seconds", type=float, default=60.0, help="narration budget (default: %(default)s)")

    s = subs.add_parser("scaffold", help="create the project")
    s.add_argument("digest")
    s.add_argument("--name", help="project name (default: the repo name)")
    s.add_argument("--speech-seconds", type=float, default=60.0)
    add_common(s)

    s = subs.add_parser("voice", help="synthesize, choose takes, fix timing, run the facts gate")
    s.add_argument("project")
    s.add_argument("--only", help="comma-separated line ids to redo (after rewording them)")
    add_common(s)
    add_voice_args(s)

    s = subs.add_parser("rebuild", help="write index.html and voiceover.json again from the digest and the clips (no model, no network)")
    s.add_argument("project")
    add_common(s)

    s = subs.add_parser("render", help="levels, check, render, measure, README and preview.json")
    s.add_argument("project")
    s.add_argument("--asr-python")
    s.add_argument("--asr-hf-home")
    s.add_argument("--preview", action="store_true", help="also build the playable preview page in build/")
    add_common(s)

    s = subs.add_parser("all", help="scaffold, voice and render")
    s.add_argument("digest")
    s.add_argument("--name")
    s.add_argument("--speech-seconds", type=float, default=60.0)
    s.add_argument("--preview", action="store_true")
    add_common(s)
    add_voice_args(s)

    args = ap.parse_args()
    if args.command == "plan":
        cmd_plan(args)
    elif args.command == "scaffold":
        cmd_scaffold(args)
    elif args.command == "voice":
        cmd_voice(args)
    elif args.command == "rebuild":
        cmd_rebuild(args)
    elif args.command == "render":
        cmd_render(args)
    else:
        project = cmd_scaffold(args)
        args.only = None
        cmd_voice(args, project)
        cmd_render(args, project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
