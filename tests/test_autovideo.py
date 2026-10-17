"""Tests of scripts/autovideo against a fake MoneyPrinterTurbo checkout (a cli.py that writes real tiny media with ffmpeg).

    python3 -m unittest discover -s tests -v
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from autovideo import cli, engine_mpt, pack as packmod, qa, runner, transcript  # noqa: E402

SECRET = "PEXELS-SECRET-KEY-12345"

# Same contract as MPT's cli.py: --batch-file <jsonl> --stop-at video; one JSON summary on stdout, logs on stderr.
FAKE_CLI = textwrap.dedent('''
    import json, pathlib, subprocess, sys, uuid
    manifest = sys.argv[sys.argv.index("--batch-file") + 1]
    p = json.loads(open(manifest, encoding="utf-8").readline())
    subject, tid = p["video_subject"], str(uuid.uuid4())
    print("log line with key " + "%(secret)s", file=sys.stderr)
    entry = {"index": 1, "task_id": tid, "status": "succeeded", "result": None, "failed_stage": None, "error": None}
    if "FAIL" in subject:
        entry.update(status="failed", failed_stage="audio", error="TTS said no, key %(secret)s")
        print(json.dumps({"total": 1, "succeeded": 0, "failed": 1, "tasks": [entry]})); sys.exit(1)
    d = pathlib.Path("storage/tasks") / tid
    d.mkdir(parents=True)
    w, h = {"9:16": (108, 192), "16:9": (192, 108), "1:1": (128, 128)}[p["video_aspect"]]
    if "WRONGSHAPE" in subject:
        w, h = h, w
    dur = 3
    audio = "anullsrc=r=22050:cl=mono" if "SILENT" in subject else "sine=frequency=300:sample_rate=22050"
    def ff(*a):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    ff("-f", "lavfi", "-i", audio, "-t", str(dur), str(d / "audio.mp3"))
    ff("-f", "lavfi", "-i", f"color=c=blue:s={w}x{h}:d={dur}:r=10", "-i", str(d / "audio.mp3"), "-shortest", "-pix_fmt", "yuv420p", str(d / "final-1.mp4"))
    srt = ""
    if "NOSUB" not in subject and p["subtitle_enabled"]:
        words = p["video_script"].split()
        lines = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)]
        step = dur / len(lines)
        for n, line in enumerate(lines):
            a, b = n * step, (n + 1) * step
            stamp = lambda s: "00:00:%%02d,%%03d" %% (int(s), round((s - int(s)) * 1000))
            srt += f"{n + 1}\\n{stamp(a)} --> {stamp(b)}\\n{line}\\n\\n"
        (d / "subtitle.srt").write_text(srt, encoding="utf-8")
    entry["result"] = {"videos": [str(d / "final-1.mp4")], "audio_file": "" if "NONARRATION" in subject else str(d / "audio.mp3"), "audio_duration": float(dur),
                       "subtitle_path": str(d / "subtitle.srt") if srt else "", "warnings": None}
    print(json.dumps({"total": 1, "succeeded": 1, "failed": 0, "tasks": [entry]}))
''') % {"secret": SECRET}

SCENES = [
    {"narration": "Xin chào các bạn, hôm nay mình giới thiệu một công cụ làm video.", "terms": ["laptop", "coding"]},
    {"narration": "Chỉ cần một chủ đề, máy sẽ viết lời đọc và dựng hình.", "terms": ["video editing"]},
]


def fake_mpt(root: Path, pexels_key: bool = True, subtitle_provider: str = "edge") -> engine_mpt.MptEnv:
    home = root / "mpt"
    (home / "app").mkdir(parents=True)
    (home / "resource" / "fonts").mkdir(parents=True)
    (home / "resource" / "fonts" / "BeVietnamPro-Bold.ttf").write_bytes(b"")
    (home / "resource" / "songs").mkdir()
    (home / "resource" / "songs" / "output000.mp3").write_bytes(b"")  # MPT ships its own songs, and a pack asks for random music by default
    (home / "cli.py").write_text(FAKE_CLI, encoding="utf-8")
    key = f'"{SECRET}"' if pexels_key else ""
    (home / "config.toml").write_text(f'[app]\npexels_api_keys = [{key}]\nsubtitle_provider = "{subtitle_provider}"\nllm_provider = "moonshot"\n', encoding="utf-8")
    return engine_mpt.MptEnv(home.resolve(), (sys.executable,))


def video(vid="01-first", title="Video", **extra):
    return {"id": vid, "title": title, "scenes": SCENES, **extra}


def write_pack(root: Path, videos, defaults=None, batch="test-batch") -> Path:
    path = root / "pack.json"
    path.write_text(json.dumps({"batch": batch, "defaults": {"target_seconds": [1, 30], **(defaults or {})}, "videos": videos}, ensure_ascii=False), encoding="utf-8")
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class FakeMptCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = fake_mpt(self.root)
        self.out = self.root / "out"
        self.logs: list[str] = []

    def tearDown(self):
        self._tmp.cleanup()

    def run_pack(self, videos, defaults=None, env=None, **kw):
        pack = packmod.load_pack(write_pack(self.root, videos, defaults))
        return runner.run(pack, env or self.env, self.out, log=self.logs.append, **kw), pack

    def state(self):
        return json.loads((self.out / "test-batch" / "state.json").read_text())["jobs"]

    def renders(self) -> int:
        """How many times the fake MPT ran (it makes one task folder per run)."""
        tasks = self.env.home / "storage" / "tasks"
        return len(list(tasks.glob("*"))) if tasks.exists() else 0


class PackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def problems(self, videos, defaults=None):
        with self.assertRaises(packmod.PackError) as ctx:
            packmod.load_pack(write_pack(self.root, videos, defaults))
        return "\n".join(ctx.exception.problems)

    def test_single_file_gets_defaults_and_vietnamese_font(self):
        job = packmod.load_pack(write_pack(self.root, [video()])).jobs[0]
        self.assertEqual((job.language, job.aspect, job.voice, job.font), ("vi-VN", "9:16", "vi-VN-HoaiMyNeural", "BeVietnamPro-Bold.ttf"))
        self.assertEqual(job.terms, ("laptop", "coding", "video editing"))
        self.assertEqual(job.script.count("\n"), 1)

    def test_directory_form_one_file_per_video(self):
        (self.root / "videos").mkdir()
        (self.root / "pack.json").write_text(json.dumps({"batch": "dir-batch", "defaults": {"target_seconds": [1, 30]}}))
        for vid in ("02-b", "01-a"):
            (self.root / "videos" / f"{vid}.json").write_text(json.dumps(video(vid)))
        pack = packmod.load_pack(self.root)
        self.assertEqual([j.id for j in pack.jobs], ["01-a", "02-b"])

    def test_directory_file_name_must_match_id(self):
        (self.root / "videos").mkdir()
        (self.root / "pack.json").write_text(json.dumps({"batch": "b"}))
        (self.root / "videos" / "x.json").write_text(json.dumps(video("01-a")))
        with self.assertRaises(packmod.PackError) as ctx:
            packmod.load_pack(self.root)
        self.assertIn("file name must be <id>.json", str(ctx.exception))

    def test_all_problems_are_reported_at_once(self):
        text = self.problems([
            {"id": "Bad Id", "title": "", "scenes": [{"narration": ""}], "colour": "red"},
            video("02-ok", voice="en-US-AriaNeural"),
            video("02-ok", aspect="4:3"),
        ])
        for expected in ("id: must be lowercase", "title:", "narration:", "unknown key 'colour'", "reads en, but the language is vi-VN", "aspect:", "used more than once"):
            self.assertIn(expected, text)

    def test_online_source_needs_search_terms_and_local_needs_files(self):
        no_terms = {"id": "01-a", "title": "T", "scenes": [{"narration": "Xin chào."}]}
        self.assertIn("give search terms", self.problems([no_terms]))
        self.assertIn("list the video or image files", self.problems([video()], {"material_source": "local"}))
        self.assertIn("no such file", self.problems([video()], {"material_source": "local", "materials": ["missing.mp4"]}))

    def test_a_local_input_that_cannot_be_read_is_a_problem_in_the_pack(self):
        (self.root / "c.mp4").write_bytes(b"aaaa")
        (self.root / "a.mp3").write_bytes(b"bbbb")
        defaults = {"material_source": "local", "materials": ["c.mp4"], "audio_file": "a.mp3", "subtitles": False}
        packmod.load_pack(write_pack(self.root, [video()], defaults))  # readable: fine
        # (these tests run as root, which can read anything, so the failure is simulated)
        with mock.patch.object(packmod, "open", side_effect=PermissionError(13, "Permission denied"), create=True):
            text = self.problems([video()], defaults)
        self.assertIn(".materials[0]: cannot read", text)
        self.assertIn(".audio_file: cannot read", text)
        self.assertIn("Permission denied", text)

    def test_music_and_narration_formats_follow_what_mpt_accepts(self):
        # MPT's SUPPORTED_BGM_EXTENSIONS: mp3 m4a aac wav flac ogg opus wma, compared in lower case (app/services/bgm.py)
        for name in ("song.mp3", "song.opus", "song.wma", "Song.OPUS", "Track 01 (live).WMA"):
            packmod.load_pack(write_pack(self.root, [video()], {"bgm": name}))
        for name in ("song.mp4", "song.txt", "song", "../song.mp3", "dir/song.mp3"):
            self.assertIn("bgm: must be none, random or a music file name", self.problems([video()], {"bgm": name}), name)
        # A narration audio_file is narrower: MPT's CLI refuses any suffix but mp3 wav m4a aac flac ogg (_CUSTOM_AUDIO_EXTENSIONS in cli.py, lower-cased)
        for name in ("voice.mp3", "voice.WAV", "voice.Flac"):
            (self.root / name).write_bytes(b"x")
            packmod.load_pack(write_pack(self.root, [video()], {"audio_file": name, "subtitles": False}))
        for name in ("voice.opus", "voice.WMA"):
            (self.root / name).write_bytes(b"x")  # it exists, and MPT would still refuse the whole manifest
            self.assertIn(f"audio_file: {name} is not one of", self.problems([video()], {"audio_file": name, "subtitles": False}), name)

    def test_subtitle_font_extension_is_compared_without_regard_to_case(self):
        # MPT's CLI: font_path.lower().endswith((".ttf", ".ttc"))
        for name in ("Vietnamese.TTF", "Font.TTC", "BeVietnamPro-Bold.ttf", "My Font.Ttf"):
            packmod.load_pack(write_pack(self.root, [video()], {"font": name}))
        for name in ("font.otf", "font", "font.ttf.txt", "dir/font.ttf"):
            self.assertIn("font: must be a .ttf or .ttc font file name", self.problems([video()], {"font": name}), name)

    def test_font_and_music_names_only_need_to_be_a_bare_file_name_with_the_right_suffix(self):
        # MPT puts no limit on the characters of a font or music name: it checks the suffix, and that the real path stays inside its folder
        for name in ("Noto Sans (Condensed).ttf", "Café Font.ttf", "A+B.TTC", "It's [bold] & fine.ttf"):
            packmod.load_pack(write_pack(self.root, [video()], {"font": name}))
        for name in ("Rock & Roll.mp3", "Don't Stop.mp3", "Tình ca + remix [2026].wma", "a;b,c=d.OGG"):
            packmod.load_pack(write_pack(self.root, [video()], {"bgm": name}))
        # but it stays one name inside the folder: no folder part, no control character, and MPT's own staging prefix is not selectable
        for name in ("a/b.ttf", "a\\b.ttf", "..", ".ttf", "x.ttf\n", "x\u0000.ttf", "x\ny.ttf", ""):
            self.assertIn("font:", self.problems([video()], {"font": name}), repr(name))
        for name in ("a/b.mp3", "a\\b.mp3", ".mp3", "x.mp3\n", "x\ty.mp3", ".bgm-upload-x.mp3", ".BGM-UPLOAD-x.mp3", ""):
            self.assertIn("bgm: must be none, random", self.problems([video()], {"bgm": name}), repr(name))  # (the empty name is caught one check earlier)

    def test_text_that_is_printed_cannot_carry_control_characters(self):
        # the title and the file names are written to the terminal by plan and run, so a newline or an escape sequence in them could forge a log line
        for bad in ("Line one\nline two", "Tab\there", "red \x1b[2J clear", "nul\x00", "cr\rreturn", "sep\u2028x", "c1\x85x"):
            self.assertIn("title: must be one line", self.problems([video(title=bad)]), repr(bad))
        text = self.problems([video()], {"material_source": "local", "materials": ["a\nb.mp4"]})
        self.assertIn("control characters", text)

    def test_tts_unfriendly_text_is_a_warning_not_an_error(self):
        scenes = [{"narration": "Xem tại https://example.com **ngay**", "terms": ["a"]}]
        pack = packmod.load_pack(write_pack(self.root, [{"id": "01-a", "title": "T", "scenes": scenes}]))
        self.assertEqual(len(pack.warnings), 2)

    def test_fingerprint_follows_words_not_qa_limits(self):
        base = packmod.load_pack(write_pack(self.root, [video()])).jobs[0].fingerprint()
        same = packmod.load_pack(write_pack(self.root, [video()], {"target_seconds": [5, 50]})).jobs[0].fingerprint()
        other = packmod.load_pack(write_pack(self.root, [video(title="Video", scenes=[{"narration": "Khác.", "terms": ["x"]}])])).jobs[0].fingerprint()
        self.assertEqual(base, same)
        self.assertNotEqual(base, other)

    def test_fingerprint_follows_file_content_not_only_size(self):
        clip = self.root / "c.mp4"
        clip.write_bytes(b"aaaa")
        make = lambda: packmod.load_pack(write_pack(self.root, [video()], {"material_source": "local", "materials": ["c.mp4"]})).jobs[0]
        before = make().fingerprint()
        self.assertEqual(make().fingerprint(), before)
        clip.write_bytes(b"bbbb")  # same size, other content
        self.assertNotEqual(make().fingerprint(), before)

    def test_relative_mpt_python_is_resolved_against_the_callers_directory(self):
        env = fake_mpt(self.root)
        (self.root / "bin").mkdir()
        (self.root / "bin" / "py").write_text("")
        (self.root / "bin" / "py").chmod(0o755)
        with contextlib.chdir(self.root):
            located = engine_mpt.locate(str(env.home), "bin/py")
        self.assertEqual(located.python, (str((self.root / "bin" / "py").resolve()),))
        self.assertEqual(engine_mpt.locate(str(env.home), "python3").python, ("python3",))

    def test_preflight_asks_only_for_what_the_engine_will_read(self):
        env = fake_mpt(self.root)  # has BeVietnamPro-Bold.ttf, a Pexels key, and neither STHeitiMedium.ttc nor any music file
        job = lambda **d: packmod.load_pack(write_pack(self.root, [video()], d)).jobs[0]
        # MPT checks the font only when subtitles are on, and the custom music file only when its volume is above zero
        self.assertIsNone(runner.preflight(env, job(font="Missing.ttf", subtitles=False)))
        self.assertIn("font Missing.ttf", runner.preflight(env, job(font="Missing.ttf", subtitles=True)))
        self.assertIsNone(runner.preflight(env, job(bgm="missing.mp3", bgm_volume=0)))
        self.assertIn("music file missing.mp3", runner.preflight(env, job(bgm="missing.mp3", bgm_volume=0.2)))

    def test_input_digests_follow_the_files_mpt_reads_by_name(self):
        env = fake_mpt(self.root)  # has resource/fonts/BeVietnamPro-Bold.ttf, empty
        songs = env.home / "resource" / "songs"
        songs.mkdir(exist_ok=True)
        job = lambda **d: packmod.load_pack(write_pack(self.root, [video()], d)).jobs[0]
        empty = hashlib.sha256(b"").hexdigest()
        self.assertEqual(engine_mpt.input_digests(env, job(bgm="none")), {"font": empty})  # no custom music: only the subtitle font
        (songs / "foo.mp3").write_bytes(b"aaaa")
        first = engine_mpt.input_digests(env, job(bgm="foo.mp3"))
        self.assertEqual(first, {"bgm": hashlib.sha256(b"aaaa").hexdigest(), "font": empty})
        (songs / "foo.mp3").write_bytes(b"bbbb")  # same name, same size, other music
        self.assertNotEqual(engine_mpt.input_digests(env, job(bgm="foo.mp3")), first)
        (env.home / "storage" / "bgm").mkdir(parents=True)
        (env.home / "storage" / "bgm" / "foo.mp3").write_bytes(b"cccc")  # MPT looks in storage/bgm before resource/songs
        self.assertEqual(engine_mpt.input_digests(env, job(bgm="foo.mp3"))["bgm"], hashlib.sha256(b"cccc").hexdigest())
        (env.home / "resource" / "fonts" / "BeVietnamPro-Bold.ttf").write_bytes(b"other font")
        self.assertEqual(engine_mpt.input_digests(env, job(bgm="none"))["font"], hashlib.sha256(b"other font").hexdigest())
        self.assertNotIn("font", engine_mpt.input_digests(env, job(subtitles=False)))  # MPT reads the font only for subtitles
        for kind in ({"bgm": "none"}, {"bgm": "random"}, {"bgm": "foo.mp3", "bgm_volume": 0}):
            self.assertNotIn("bgm", engine_mpt.input_digests(env, job(**kind)), kind)  # no custom music that is read
        self.assertEqual(engine_mpt.input_digests(env, job(bgm="missing.mp3"))["bgm"], engine_mpt.FILE_MISSING)  # asked for and gone
        self.assertEqual(engine_mpt.input_digests(env, job(font="Gone.ttf"))["font"], engine_mpt.FILE_MISSING)

    def test_a_font_or_music_file_that_links_outside_mpts_folder_is_not_usable(self):
        env = fake_mpt(self.root)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "font.ttf").write_bytes(b"f")
        (outside / "song.mp3").write_bytes(b"s")
        fonts, songs, uploads = env.home / "resource" / "fonts", env.home / "resource" / "songs", env.home / "storage" / "bgm"
        songs.mkdir(exist_ok=True)
        uploads.mkdir(parents=True)
        (fonts / "Linked.ttf").symlink_to(outside / "font.ttf")
        (uploads / "song.mp3").symlink_to(outside / "song.mp3")
        job = lambda **d: packmod.load_pack(write_pack(self.root, [video()], d)).jobs[0]
        # MPT resolves real paths and refuses a file that leaves its folder (cli.py _resolve_managed_resource_file, bgm.py resolve_bgm_file)
        self.assertIn("outside", runner.preflight(env, job(font="Linked.ttf")))
        self.assertEqual(engine_mpt.input_digests(env, job(font="Linked.ttf"))["font"], engine_mpt.FILE_MISSING)
        self.assertIn("outside", runner.preflight(env, job(bgm="song.mp3")))
        (songs / "song.mp3").write_bytes(b"real")  # MPT then tries its next folder, and a real file there is used
        self.assertIsNone(runner.preflight(env, job(bgm="song.mp3")))
        self.assertEqual(engine_mpt.input_digests(env, job(bgm="song.mp3"))["bgm"], hashlib.sha256(b"real").hexdigest())
        (fonts / "Inner.ttf").symlink_to(fonts / "BeVietnamPro-Bold.ttf")  # a link that stays inside the folder is fine
        self.assertIsNone(runner.preflight(env, job(font="Inner.ttf")))

    def test_random_music_needs_a_music_file_in_mpts_folders(self):
        env = fake_mpt(self.root)  # ships one song, like MPT's resource/songs
        job = lambda **d: packmod.load_pack(write_pack(self.root, [video()], d)).jobs[0]
        self.assertIsNone(runner.preflight(env, job()))  # bgm defaults to random, at volume 0.2
        songs = env.home / "resource" / "songs"
        (songs / "output000.mp3").unlink()
        # MPT then renders without music and says nothing (get_bgm_file returns ""), and a voiced video passes QA all the same
        no_music = 'set bgm to "none"'
        self.assertIn(no_music, runner.preflight(env, job()))
        self.assertIsNone(runner.preflight(env, job(bgm="none")))
        self.assertIsNone(runner.preflight(env, job(bgm_volume=0)))  # at volume 0 MPT skips the music anyway
        (songs / "notes.txt").write_bytes(b"x")
        (songs / ".bgm-upload-half.mp3").write_bytes(b"x")  # MPT's staging file, never picked
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"x")
        (songs / "link.mp3").symlink_to(outside)  # a link out of the folder is refused by MPT
        self.assertIn(no_music, runner.preflight(env, job()))
        (env.home / "storage" / "bgm").mkdir(parents=True)
        (env.home / "storage" / "bgm" / "mine.OPUS").write_bytes(b"x")  # an uploaded song counts
        self.assertIsNone(runner.preflight(env, job()))

    def test_a_file_that_cannot_be_read_is_a_problem_not_a_traceback(self):
        env = fake_mpt(self.root)
        job = packmod.load_pack(write_pack(self.root, [video()])).jobs[0]
        unreadable = mock.patch.object(engine_mpt.hashlib, "file_digest", side_effect=PermissionError(13, "Permission denied"))
        with unreadable:  # (these tests run as root, which can read anything, so the failure is simulated)
            self.assertEqual(engine_mpt.input_digests(env, job), {"font": engine_mpt.FILE_UNREADABLE})
            self.assertIn("cannot be read", runner.preflight(env, job))
            summary = runner.run(packmod.load_pack(write_pack(self.root, [video()])), env, self.root / "out", log=lambda line: None)
            self.assertEqual((summary["failed"], summary["videos"][0]["stage"]), (1, "preflight"))
            self.assertIn("cannot be read", summary["videos"][0]["error"])
        self.assertEqual(engine_mpt.input_digests(env, job)["font"], hashlib.sha256(b"").hexdigest())  # readable again

    def test_preflight_names_a_missing_ffmpeg_or_ffprobe(self):
        env = fake_mpt(self.root)
        job = packmod.load_pack(write_pack(self.root, [video()])).jobs[0]
        self.assertIsNone(runner.preflight(env, job))
        for gone in ("ffmpeg", "ffprobe"):
            with mock.patch.object(runner.shutil, "which", lambda name, gone=gone: None if name == gone else f"/usr/bin/{name}"):
                self.assertIn(gone, runner.preflight(env, job))

    def test_preflight_reads_subtitle_provider_the_way_mpt_does(self):
        (self.root / "voice.mp3").write_bytes(b"x")
        job = packmod.load_pack(write_pack(self.root, [video(audio_file="voice.mp3")])).jobs[0]  # audio_file with subtitles: needs whisper
        for index, written in enumerate(("whisper", "  Whisper ", "WHISPER")):
            home = self.root / f"home-{index}"
            home.mkdir()
            self.assertIsNone(runner.preflight(fake_mpt(home, subtitle_provider=written), job), repr(written))  # MPT strips and lowercases it
        other = self.root / "home-edge"
        other.mkdir()
        self.assertIn("whisper", runner.preflight(fake_mpt(other, subtitle_provider=" Edge "), job))

    def test_locate_takes_the_checkouts_own_python_only_when_it_can_run(self):
        env = fake_mpt(self.root)  # a checkout without a .venv
        venv = env.home / ".venv" / "bin"
        venv.mkdir(parents=True)
        python = venv / "python"
        python.write_text("")  # a file, but not executable
        with mock.patch.dict(os.environ), mock.patch.object(engine_mpt.shutil, "which", lambda name: None):  # and no uv to fall back on
            os.environ.pop("MPT_PYTHON", None)
            with self.assertRaises(engine_mpt.MptError) as ctx:
                engine_mpt.locate(str(env.home))
            self.assertIn(".venv", str(ctx.exception))
            python.chmod(0o755)
            self.assertEqual(engine_mpt.locate(str(env.home)).python, (str(python),))

    def test_locate_refuses_a_python_that_cannot_run(self):
        env = fake_mpt(self.root)
        (self.root / "plain.txt").write_text("not executable")
        for bad in (str(self.root / "missing" / "python"), "no-such-command-anywhere", str(self.root / "plain.txt")):
            with self.assertRaises(engine_mpt.MptError, msg=bad) as ctx:
                engine_mpt.locate(str(env.home), bad)
            self.assertIn("--mpt-python", str(ctx.exception))

    def test_mpt_params_for_each_kind_of_job(self):
        job = packmod.load_pack(write_pack(self.root, [video(bgm="none")])).jobs[0]
        params = engine_mpt.video_params(job)
        self.assertEqual((params["video_source"], params["bgm_type"], params["voice_name"]), ("pexels", "", "vi-VN-HoaiMyNeural"))
        self.assertEqual(params["video_terms"], ["laptop", "coding", "video editing"])
        clip, audio = self.root / "c.mp4", self.root / "a.mp3"
        clip.write_bytes(b"x"); audio.write_bytes(b"x")
        local = packmod.load_pack(write_pack(self.root, [video()], {"material_source": "local", "materials": ["c.mp4"], "audio_file": "a.mp3", "subtitles": False})).jobs[0]
        params = engine_mpt.video_params(local)
        self.assertEqual(params["video_materials"], [{"provider": "local", "url": str(clip.resolve()), "duration": 0}])
        self.assertEqual(params["custom_audio_file"], str(audio.resolve()))
        self.assertNotIn("voice_name", params)
        self.assertNotIn("video_terms", params)

    def test_font_extension_matches_what_mpt_accepts(self):
        self.assertIn("font", self.problems([video()], {"font": "Some-Font.otf"}))  # MPT's batch check: .ttf or .ttc only
        job = packmod.load_pack(write_pack(self.root, [video()], {"font": "STHeitiMedium.ttc"})).jobs[0]
        self.assertEqual(job.font, "STHeitiMedium.ttc")

    def test_paid_sources_are_not_available(self):
        self.assertIn("material_source", self.problems([video()], {"material_source": "wavespeed"}))


class TranscriptTests(unittest.TestCase):
    SRT = "1\n00:00:00,000 --> 00:00:01,500\nXin chào các bạn\n\n2\n00:00:01,500 --> 00:00:03,000\nhôm nay mình học\n\n3\n00:00:03,000 --> 00:00:04,000\nvề video\n"

    def test_parse_and_coverage(self):
        cues = transcript.parse_srt(self.SRT)
        self.assertEqual([(c.start, c.end) for c in cues], [(0.0, 1.5), (1.5, 3.0), (3.0, 4.0)])
        self.assertEqual(transcript.coverage("Xin chào các bạn, hôm nay mình học về video.", cues), 1.0)
        self.assertLess(transcript.coverage("Xin chào các bạn, hôm nay mình học về video và âm thanh nữa nhé.", cues), 0.8)

    def test_decomposed_diacritics_still_match(self):
        import unicodedata
        cues = transcript.parse_srt(unicodedata.normalize("NFD", self.SRT))
        self.assertEqual(transcript.coverage("Xin chào các bạn", cues), 1.0)

    def test_scene_times_follow_word_counts(self):
        cues = transcript.parse_srt(self.SRT)
        times = transcript.scene_times(["Xin chào các bạn", "hôm nay mình học về video"], cues)
        self.assertEqual(times[0], (0.0, 1.5))
        self.assertEqual(times[1], (1.5, 4.0))

    def test_scene_times_refuse_when_lengths_disagree(self):
        cues = transcript.parse_srt(self.SRT)
        self.assertEqual(transcript.scene_times(["một hai ba bốn năm sáu bảy tám chín mười mười một mười hai"], cues), [None])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class RunnerTests(FakeMptCase):
    def test_renders_and_stores_video_audio_transcript_report(self):
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["failed"], summary["qa_failed"]), (1, 0, 0))
        folder = self.out / "test-batch" / "01-first"
        for name in ("video.mp4", "narration.mp3", "subtitles.srt", "transcript.txt", "transcript.json", "job.json", "report.json", "mpt.log"):
            self.assertTrue((folder / name).is_file(), name)
        report = json.loads((folder / "report.json").read_text())
        self.assertEqual(report["status"], "done")
        self.assertTrue(all(c["ok"] for c in report["checks"] if c["level"] == "error"))
        doc = json.loads((folder / "transcript.json").read_text())
        self.assertEqual(len(doc["scenes"]), 2)
        self.assertIsNotNone(doc["scenes"][0]["start"])
        self.assertTrue((self.out / "test-batch" / "summary.md").is_file())

    def test_rerun_skips_done_jobs_and_rerenders_an_edited_one(self):
        self.run_pack([video("01-a"), video("02-b")])
        summary, _ = self.run_pack([video("01-a"), video("02-b")])
        self.assertEqual((summary["done"], summary["skipped"]), (0, 2))
        edited = video("02-b", scenes=[{"narration": "Lời mới hoàn toàn khác nhé các bạn ơi.", "terms": ["x"]}])
        summary, _ = self.run_pack([video("01-a"), edited])
        self.assertEqual((summary["done"], summary["skipped"]), (1, 1))

    def test_force_and_only(self):
        self.run_pack([video("01-a"), video("02-b")])
        summary, _ = self.run_pack([video("01-a"), video("02-b")], only=["02-b"], force=True)
        self.assertEqual([r["id"] for r in summary["videos"]], ["02-b"])
        self.assertEqual(summary["done"], 1)
        with self.assertRaises(ValueError):
            self.run_pack([video()], only=["nope"])

    def test_failed_job_does_not_stop_the_batch_and_secrets_are_removed(self):
        summary, _ = self.run_pack([video("01-a", title="FAIL here"), video("02-b")], retries=1)
        self.assertEqual((summary["failed"], summary["done"]), (1, 1))
        folder = self.out / "test-batch" / "01-a"
        report = json.loads((folder / "report.json").read_text())
        self.assertEqual((report["status"], report["stage"], report["attempts"]), ("failed", "audio", 2))
        for text in (json.dumps(report), (folder / "mpt.log").read_text(), json.dumps(self.state()), json.dumps(summary)):
            self.assertNotIn(SECRET, text)
        self.assertIn("***", report["error"])

    def test_silent_audio_and_wrong_shape_fail_qa(self):
        summary, _ = self.run_pack([video("01-a", title="SILENT"), video("02-b", title="WRONGSHAPE")], retries=0)
        self.assertEqual(summary["qa_failed"], 2)
        by_id = {r["id"]: r["qa_failures"] for r in summary["videos"]}
        self.assertIn("audible", by_id["01-a"])
        self.assertIn("aspect", by_id["02-b"])
        self.assertEqual(self.state()["01-a"]["status"], "qa_failed")

    def test_success_without_a_narration_file_fails_qa(self):
        summary, _ = self.run_pack([video(title="NONARRATION")], retries=0)
        self.assertEqual(summary["videos"][0]["status"], "qa_failed")
        self.assertIn("narration_made", summary["videos"][0]["qa_failures"])

    def test_missing_subtitles_fail_qa_when_requested(self):
        summary, _ = self.run_pack([video(title="NOSUB")], retries=0)
        self.assertIn("subtitles_made", summary["videos"][0]["qa_failures"])

    def test_audio_file_job_without_subtitles_fails_qa(self):
        (self.root / "voice.mp3").write_bytes(b"x")
        env = fake_mpt(self.root / "whisper", subtitle_provider="whisper") if (self.root / "whisper").mkdir() is None else None
        summary, _ = self.run_pack([video(title="NOSUB", audio_file="voice.mp3")], env=env, retries=0)
        self.assertEqual(summary["videos"][0]["status"], "qa_failed")
        self.assertIn("subtitles_made", summary["videos"][0]["qa_failures"])

    def test_relative_output_root_still_reaches_mpt(self):
        pack = packmod.load_pack(write_pack(self.root, [video()]))
        with contextlib.chdir(self.root):
            summary = runner.run(pack, self.env, Path("rel-out"), log=self.logs.append)
        self.assertEqual((summary["done"], summary["failed"]), (1, 0))
        self.assertTrue((self.root / "rel-out" / "test-batch" / "01-first" / "video.mp4").is_file())

    def test_preflight_stops_before_mpt_starts(self):
        env = fake_mpt(self.root / "nokey", pexels_key=False) if (self.root / "nokey").mkdir() is None else None
        summary, _ = self.run_pack([video()], env=env)
        self.assertEqual(summary["videos"][0]["stage"], "preflight")
        self.assertIn("pexels_api_keys", summary["videos"][0]["error"])
        self.assertFalse(list((self.env.home / "storage").glob("*")) if (self.env.home / "storage").exists() else [])

    def test_requalify_uses_new_limits_without_rendering(self):
        self.run_pack([video()])
        pack = packmod.load_pack(write_pack(self.root, [video()], {"target_seconds": [10, 30]}))
        rows = runner.requalify(pack, self.out)
        self.assertEqual(rows[0]["status"], "qa_failed")
        self.assertEqual(self.state()["01-first"]["status"], "qa_failed")
        pack = packmod.load_pack(write_pack(self.root, [video()], {"target_seconds": [1, 30]}))
        self.assertEqual(runner.requalify(pack, self.out)[0]["status"], "done")

    def test_qa_does_not_bless_a_video_left_over_from_before_a_failed_rerender(self):
        self.run_pack([video()])
        edited = packmod.load_pack(write_pack(self.root, [video(title="FAIL after the edit")]))
        summary = runner.run(edited, self.env, self.out, retries=0, log=self.logs.append)
        self.assertEqual(summary["failed"], 1)
        folder = self.out / "test-batch" / "01-first"
        self.assertTrue((folder / "video.mp4").is_file())  # the old video is still there, and it is not the new job's
        rows = runner.requalify(edited, self.out)
        self.assertEqual(rows[0]["status"], "stale")
        self.assertEqual(self.state()["01-first"]["status"], "failed")

    def test_a_failed_forced_render_leaves_nothing_that_qa_can_call_done(self):
        self.run_pack([video()])
        (self.env.home / "cli.py").write_text("import sys\nsys.exit(1)\n")  # the next render fails; the job itself is unchanged
        summary, pack = self.run_pack([video()], force=True, retries=0)
        self.assertEqual(summary["failed"], 1)
        self.assertTrue((self.out / "test-batch" / "01-first" / "video.mp4").is_file())  # the old video is kept on disk
        self.assertEqual(runner.requalify(pack, self.out)[0]["status"], "stale")  # but it no longer counts as this job's finished render
        self.assertEqual(self.state()["01-first"]["status"], "failed")

    def test_an_interruption_between_the_state_write_and_the_old_marker_leaves_nothing_to_bless(self):
        self.run_pack([video()])
        pack = packmod.load_pack(write_pack(self.root, [video()]))
        real_write = runner.write_json

        def interrupted_when_the_job_is_marked_running(path, data):
            real_write(path, data)
            if path.name == "state.json" and data["jobs"].get("01-first", {}).get("status") == "running":
                raise KeyboardInterrupt  # Ctrl-C right after `running` reached the disk, and before anything else is done

        with mock.patch.object(runner, "write_json", interrupted_when_the_job_is_marked_running):
            with self.assertRaises(KeyboardInterrupt):
                runner.run(pack, self.env, self.out, force=True, log=self.logs.append)  # forced: the fingerprint is the same as the done render
        folder = self.out / "test-batch" / "01-first"
        self.assertIsNone(runner.rendered_fingerprint(folder))  # the old render no longer says it is finished, even at that moment
        self.assertEqual(runner.requalify(pack, self.out)[0]["status"], "stale")
        self.assertEqual(self.state()["01-first"]["status"], "running")

    def test_skip_needs_the_folder_to_hold_this_jobs_render(self):
        self.run_pack([video()])
        job_file = self.out / "test-batch" / "01-first" / "job.json"
        data = json.loads(job_file.read_text())
        job_file.write_text(json.dumps({**data, "fingerprint": "from-another-render"}))
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (1, 0))

    def test_narrowed_target_seconds_is_checked_again_without_rendering_when_it_still_holds(self):
        self.run_pack([video()])
        summary, _ = self.run_pack([video()], {"target_seconds": [2, 10]})  # the video is 3 s: still inside
        self.assertEqual((summary["done"], summary["skipped"], summary["qa_failed"]), (0, 1, 0))
        self.assertEqual(self.state()["01-first"]["qa_basis"], [2.0, 10.0])

    def test_narrowed_target_seconds_that_no_longer_holds_is_not_reported_done(self):
        self.run_pack([video()])
        summary, _ = self.run_pack([video()], {"target_seconds": [1, 2]}, retries=2)  # the video is 3 s: too long now
        self.assertEqual((summary["skipped"], summary["qa_failed"]), (0, 1))
        self.assertIn("duration", summary["videos"][0]["qa_failures"])
        self.assertEqual(self.renders(), 1)  # nothing that goes into the render changed, so it was not rendered again
        self.assertEqual(self.state()["01-first"]["status"], "qa_failed")

    def test_a_video_cut_short_after_the_render_is_rendered_again(self):
        self.run_pack([video()])
        (self.out / "test-batch" / "01-first" / "video.mp4").write_bytes(b"")
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (1, 0))
        self.assertEqual(self.renders(), 2)
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (0, 1))  # and the new render is whole

    def test_a_video_changed_without_changing_its_size_is_rendered_again(self):
        self.run_pack([video()])
        file = self.out / "test-batch" / "01-first" / "video.mp4"
        data = bytearray(file.read_bytes())
        data[len(data) // 2] ^= 0xFF  # one flipped byte: same name, same size, not the video that passed QA
        file.write_bytes(bytes(data))
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (1, 0))
        self.assertEqual(self.renders(), 2)

    def test_a_file_added_by_hand_and_accepted_by_qa_is_covered_from_then_on(self):
        summary, pack = self.run_pack([video(title="NOSUB")], retries=0)
        self.assertEqual(summary["videos"][0]["status"], "qa_failed")  # MPT made no subtitles
        folder = self.out / "test-batch" / "01-first"
        words = " ".join(scene["narration"] for scene in SCENES).split()
        lines = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)]
        stamp = lambda t: "00:00:%02d,%03d" % (int(t), round((t - int(t)) * 1000))
        step = 3 / len(lines)
        (folder / "subtitles.srt").write_text("".join(f"{n + 1}\n{stamp(n * step)} --> {stamp((n + 1) * step)}\n{line}\n\n" for n, line in enumerate(lines)), encoding="utf-8")
        self.assertEqual(runner.requalify(pack, self.out)[0]["status"], "done")  # the owner supplied them, and QA accepts the folder
        self.assertEqual(runner.job_status(self.state()["01-first"], pack.jobs[0], folder), "done")
        (folder / "subtitles.srt").unlink()  # a file QA required is gone again
        self.assertEqual(runner.job_status(self.state()["01-first"], pack.jobs[0], folder), "missing")
        summary, _ = self.run_pack([video(title="NOSUB")], retries=0)
        self.assertEqual((summary["skipped"], self.renders()), (0, 2))  # so it is not skipped as done

    def test_a_job_that_failed_qa_is_not_rendered_again_by_the_next_run(self):
        summary, _ = self.run_pack([video(title="SILENT")], retries=1)  # both attempts fail QA
        self.assertEqual((summary["qa_failed"], self.renders()), (1, 2))
        summary, _ = self.run_pack([video(title="SILENT")], retries=1)  # nothing that goes into the render changed
        self.assertEqual((summary["qa_failed"], summary["done"], summary["skipped"]), (1, 0, 0))  # still reported, and still a failure
        self.assertIn("audible", summary["videos"][0]["qa_failures"])  # with the reason it failed
        self.assertEqual(self.renders(), 2)  # but not rendered again
        summary, _ = self.run_pack([video(title="SILENT")], retries=0, force=True)  # --force is the way to try again
        self.assertEqual(self.renders(), 3)
        summary, _ = self.run_pack([video(title="SILENT", scenes=[{"narration": "Lời đã đổi hoàn toàn.", "terms": ["x"]}])], retries=0)
        self.assertEqual(self.renders(), 4)  # and so is a change to the job

    def test_a_job_that_failed_in_the_engine_is_tried_again_by_the_next_run(self):
        self.run_pack([video(title="FAIL once")], retries=0)
        self.assertEqual(self.state()["01-first"]["attempts"], 1)
        self.run_pack([video(title="FAIL once")], retries=0)
        self.assertEqual(self.state()["01-first"]["attempts"], 2)  # `failed` is retried, unlike `qa_failed`

    def test_widened_target_seconds_checks_a_qa_failed_video_again_without_rendering(self):
        self.run_pack([video()], {"target_seconds": [1, 2]}, retries=0)  # 3 s video: fails QA on duration
        self.assertEqual(self.state()["01-first"]["status"], "qa_failed")
        summary, _ = self.run_pack([video()], retries=0)  # limits back to [1, 30]: the same video passes
        self.assertEqual((summary["done"], summary["skipped"], summary["qa_failed"]), (0, 1, 0))
        self.assertEqual(self.renders(), 1)
        self.assertEqual(self.state()["01-first"]["status"], "done")

    def test_run_refuses_a_negative_retry_count(self):
        with self.assertRaises(ValueError):
            self.run_pack([video()], retries=-1)

    def test_replacing_the_custom_music_file_renders_the_job_again(self):
        songs = self.env.home / "resource" / "songs"
        songs.mkdir(parents=True, exist_ok=True)
        (songs / "foo.mp3").write_bytes(b"aaaa")
        self.run_pack([video()], {"bgm": "foo.mp3"})
        summary, _ = self.run_pack([video()], {"bgm": "foo.mp3"})
        self.assertEqual((summary["done"], summary["skipped"]), (0, 1))
        (songs / "foo.mp3").write_bytes(b"bbbb")  # same name and size, other music
        summary, _ = self.run_pack([video()], {"bgm": "foo.mp3"})
        self.assertEqual((summary["done"], summary["skipped"]), (1, 0))
        self.assertEqual(self.renders(), 2)

    def test_replacing_the_subtitle_font_file_renders_the_job_again(self):
        font = self.env.home / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"
        self.run_pack([video()])
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (0, 1))
        font.write_bytes(b"a newer version of the font")
        summary, _ = self.run_pack([video()])
        self.assertEqual((summary["done"], summary["skipped"]), (1, 0))
        self.assertEqual(self.renders(), 2)
        font.write_bytes(b"x")
        summary, _ = self.run_pack([video(subtitles=False)])  # a job without subtitles never reads the font
        self.assertEqual(self.renders(), 3)  # (it is a different job anyway: subtitles changed)
        font.write_bytes(b"y")
        summary, _ = self.run_pack([video(subtitles=False)])
        self.assertEqual((summary["done"], summary["skipped"]), (0, 1))  # and a changed font does not matter to it

    def test_a_batch_that_another_run_holds_is_refused(self):
        pack = packmod.load_pack(write_pack(self.root, [video()]))
        with runner.batch_lock(self.out / "test-batch"):
            with self.assertRaises(runner.BatchBusy):
                runner.run(pack, self.env, self.out, log=self.logs.append)
            with self.assertRaises(runner.BatchBusy):
                runner.requalify(pack, self.out)
            runner.read_state(self.out / "test-batch")  # reading is not a write: no lock needed
        self.assertEqual(runner.run(pack, self.env, self.out, log=self.logs.append)["done"], 1)  # free again once the holder is done
        self.assertEqual(self.renders(), 1)

    def test_a_deleted_custom_music_file_is_not_skipped_over(self):
        songs = self.env.home / "resource" / "songs"
        songs.mkdir(parents=True, exist_ok=True)
        (songs / "foo.mp3").write_bytes(b"aaaa")
        self.run_pack([video()], {"bgm": "foo.mp3"})
        (songs / "foo.mp3").unlink()
        summary, _ = self.run_pack([video()], {"bgm": "foo.mp3"}, retries=0)
        self.assertEqual((summary["skipped"], summary["failed"]), (0, 1))  # not "done already": the music the job needs is gone
        self.assertEqual(summary["videos"][0]["stage"], "preflight")
        self.assertEqual(self.renders(), 1)

    def test_a_python_that_cannot_start_is_a_startup_failure_not_a_traceback(self):
        broken = engine_mpt.MptEnv(self.env.home, (str(self.root / "gone" / "python"),))
        summary, _ = self.run_pack([video("01-a"), video("02-b")], env=broken, retries=2)
        self.assertEqual([r["stage"] for r in summary["videos"]], ["startup", "startup"])  # both ran, none crashed the batch
        self.assertEqual(self.state()["01-a"]["attempts"], 1)  # and a second try cannot help

    def test_timeout_kills_the_engine(self):
        (self.env.home / "cli.py").write_text("import time\ntime.sleep(60)\n")
        summary, _ = self.run_pack([video()], timeout=1, retries=3)
        self.assertEqual(summary["videos"][0]["stage"], "timeout")
        self.assertEqual(self.state()["01-first"]["attempts"], 1)  # no retry after a timeout

    def test_summary_without_task_means_startup_failure(self):
        (self.env.home / "cli.py").write_text("import sys\nprint('usage error', file=sys.stderr)\nsys.exit(2)\n")
        summary, _ = self.run_pack([video()], retries=2)
        self.assertEqual(summary["videos"][0]["stage"], "startup")
        self.assertEqual(self.state()["01-first"]["attempts"], 1)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class CliTests(FakeMptCase):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main([*argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_validate_bad_pack_exits_2_and_lists_problems(self):
        path = write_pack(self.root, [{"id": "x", "title": "T", "scenes": []}])
        code, _, err = self.call("validate", str(path))
        self.assertEqual(code, 2)
        self.assertIn("scenes: must be a list", err)

    def test_plan_json_has_params_and_flags_setup_problem(self):
        path = write_pack(self.root, [video()])
        code, out, _ = self.call("plan", str(path), "--json", "--mpt-home", str(self.env.home), "--mpt-python", sys.executable)
        plan = json.loads(out)["videos"][0]
        self.assertEqual((code, plan["problem"], plan["mpt_params"]["video_aspect"]), (0, None, "9:16"))
        nokey = fake_mpt(self.root / "nokey", pexels_key=False) if (self.root / "nokey").mkdir() is None else None
        code, out, _ = self.call("plan", str(path), "--json", "--mpt-home", str(nokey.home), "--mpt-python", sys.executable)
        self.assertEqual(code, 1)  # a batch that cannot run is not "ready", with --json as without it
        self.assertIn("pexels_api_keys", json.loads(out)["videos"][0]["problem"])

    def test_run_then_status_then_qa(self):
        path = write_pack(self.root, [video("01-a"), video("02-b", title="SILENT")])
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        code, out, _ = self.call("run", str(path), "--retries", "0", "--json", *base)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["qa_failed"], 1)
        code, out, _ = self.call("status", str(path), "--json", *base)
        self.assertEqual({r["id"]: r["status"] for r in json.loads(out)}, {"01-a": "done", "02-b": "qa_failed"})
        path = write_pack(self.root, [video("01-a", scenes=[{"narration": "Đổi lời.", "terms": ["x"]}]), video("02-b", title="SILENT")])
        code, out, _ = self.call("status", str(path), "--json", *base)
        self.assertEqual(json.loads(out)[0]["status"], "stale")

    def test_qa_with_nothing_rendered_is_not_a_pass(self):
        path = write_pack(self.root, [video()])
        base = ["--out", str(self.out)]
        code, out, _ = self.call("qa", str(path), *base)
        self.assertEqual((code, out.strip()), (1, "01-first: missing"))
        code, _, err = self.call("qa", str(path), "--only", "nope", *base)
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_status_exits_non_zero_unless_every_video_is_done(self):
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        path = write_pack(self.root, [video("01-a"), video("02-b", title="SILENT")])
        self.assertEqual(self.call("status", str(path), *base)[0], 1)  # nothing rendered yet: pending
        self.call("run", str(path), "--retries", "0", *base)
        self.assertEqual(self.call("status", str(path), *base)[0], 1)  # one video failed QA
        path = write_pack(self.root, [video("01-a")])
        self.assertEqual(self.call("status", str(path), *base)[0], 0)  # the pack now holds only the video that is done
        path = write_pack(self.root, [video("01-a", title="Changed after rendering")])
        self.assertEqual(self.call("status", str(path), *base)[0], 1)  # stale


    def test_status_looks_at_the_files_and_at_the_qa_limits_not_only_at_the_state(self):
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        path = write_pack(self.root, [video()])
        self.call("run", str(path), *base)
        status = lambda p: (lambda r: (r[0], json.loads(r[1])[0]["status"]))(self.call("status", str(p), "--json", *base))
        self.assertEqual(status(path), (0, "done"))
        folder = self.out / "test-batch" / "01-first"
        job_file = folder / "job.json"
        data = json.loads(job_file.read_text())
        job_file.write_text(json.dumps({**data, "fingerprint": "from-another-render"}))
        self.assertEqual(status(path), (1, "stale"))
        job_file.write_text(json.dumps(data))
        self.assertEqual(status(path), (0, "done"))
        self.assertEqual(status(write_pack(self.root, [video()], {"target_seconds": [1, 2]})), (1, "unchecked"))  # the limits changed, no QA since
        (folder / "video.mp4").unlink()
        self.assertEqual(status(path), (1, "missing"))

    def test_status_of_a_qa_failed_video_follows_the_limits_too(self):
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        self.call("run", str(write_pack(self.root, [video()], {"target_seconds": [1, 2]})), "--retries", "0", *base)
        status = lambda p: (lambda r: (r[0], json.loads(r[1])[0]["status"]))(self.call("status", str(p), "--json", *base))
        self.assertEqual(status(write_pack(self.root, [video()], {"target_seconds": [1, 2]})), (1, "qa_failed"))
        widened = write_pack(self.root, [video()], {"target_seconds": [1, 30]})
        self.assertEqual(status(widened), (1, "unchecked"))  # the limit that failed it is gone, but nobody looked again
        self.assertEqual(self.call("qa", str(widened), *base)[0], 0)
        self.assertEqual(status(widened), (0, "done"))

    def test_qa_after_new_limits_makes_status_truthful_again(self):
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        self.call("run", str(write_pack(self.root, [video()])), *base)
        narrow = write_pack(self.root, [video()], {"target_seconds": [1, 2]})
        self.assertEqual(self.call("qa", str(narrow), *base)[0], 1)
        self.assertEqual(json.loads(self.call("status", str(narrow), "--json", *base)[1])[0]["status"], "qa_failed")

    def test_run_rejects_negative_retries_and_unusable_timeouts(self):
        path = write_pack(self.root, [video()])
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]  # a working setup, so only the option can fail
        for bad in (["--retries", "-1"], ["--timeout", "0"], ["--timeout", "-5"], ["--timeout", "nan"], ["--timeout", "inf"]):
            code, _, err = self.call("run", str(path), *base, *bad)
            self.assertEqual(code, 2, bad)
            self.assertIn(bad[0], err)
        self.assertEqual(self.call("run", str(path), *base, "--retries", "0", "--timeout", "60")[0], 0)  # the same setup works with sane values

    def test_plan_with_no_usable_mpt_is_not_ready(self):
        path = write_pack(self.root, [video()])
        code, out, err = self.call("plan", str(path), "--json", "--mpt-home", str(self.root / "no-mpt-here"))
        self.assertEqual(code, 1)
        self.assertIn("no MoneyPrinterTurbo checkout", json.loads(out)["videos"][0]["problem"])  # the reason is in the answer, not only on stderr
        code, _, _ = self.call("plan", str(path), "--mpt-home", str(self.env.home), "--mpt-python", str(self.root / "no-python"))
        self.assertEqual(code, 1)

    def test_json_is_offered_only_by_the_commands_that_print_it(self):
        path = write_pack(self.root, [video()])
        base = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        for command in ("validate", "qa"):
            self.assertEqual(self.call(command, str(path), "--json", *base)[0], 2, command)  # the option does not exist there
        self.assertEqual(self.call("doctor", "--json", "--mpt-home", str(self.env.home))[0], 2)
        for command in ("plan", "status"):
            code, out, _ = self.call(command, str(path), "--json", *base)
            json.loads(out)  # these do print JSON

    def test_status_notices_a_damaged_or_incomplete_output_folder(self):
        path = write_pack(self.root, [video()])
        mpt = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        self.call("run", str(path), *mpt)
        folder = self.out / "test-batch" / "01-first"
        status = lambda: (lambda r: (r[0], json.loads(r[1])[0]["status"]))(self.call("status", str(path), "--json", *mpt))
        self.assertEqual(status(), (0, "done"))
        flipped = lambda f: f.write_bytes(bytes(b ^ 0xFF if i == 5 else b for i, b in enumerate(f.read_bytes())))  # same size, one byte differs
        damage = [
            ("video.mp4", lambda f: f.write_bytes(b"")),  # cut to nothing
            ("video.mp4", flipped),
            ("narration.mp3", flipped),
            ("subtitles.srt", lambda f: f.unlink()),  # a sidecar that QA asked for, deleted
            ("narration.mp3", lambda f: f.unlink()),
            ("transcript.json", lambda f: f.unlink()),
        ]
        for name, harm in damage:
            file = folder / name
            original = file.read_bytes()
            harm(file)
            self.assertEqual(status(), (1, "missing"), name)
            self.assertEqual(self.call("qa", str(path), *mpt)[0], 1, name)  # and QA does not pass what is not whole
            file.write_bytes(original)
            self.assertEqual(status(), (0, "done"), name)

    def test_status_and_qa_notice_a_replaced_music_file_when_they_can_find_mpt(self):
        songs = self.env.home / "resource" / "songs"
        songs.mkdir(parents=True, exist_ok=True)
        (songs / "foo.mp3").write_bytes(b"aaaa")
        path = write_pack(self.root, [video()], {"bgm": "foo.mp3"})
        mpt = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        no_mpt = ["--out", str(self.out), "--mpt-home", str(self.root / "no-mpt-here")]
        self.call("run", str(path), *mpt)
        status = lambda args: json.loads(self.call("status", str(path), "--json", *args)[1])[0]["status"]
        self.assertEqual(status(mpt), "done")
        (songs / "foo.mp3").write_bytes(b"bbbb")
        self.assertEqual(status(mpt), "stale")  # the music changed after the render
        self.assertEqual(self.call("qa", str(path), *mpt)[0], 1)  # and QA does not pass the old video for the new music
        (songs / "foo.mp3").write_bytes(b"aaaa")
        self.assertEqual(status(mpt), "done")  # the music it was rendered with is back
        (songs / "foo.mp3").unlink()
        self.assertEqual(status(mpt), "stale")  # the music it needs is gone
        self.assertEqual(status(no_mpt), "done")  # without MPT the file cannot be read, so nothing is claimed about it

    def test_status_notices_a_replaced_font_when_it_can_find_mpt(self):
        path = write_pack(self.root, [video()])
        mpt = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        no_mpt = ["--out", str(self.out), "--mpt-home", str(self.root / "no-mpt-here")]
        self.call("run", str(path), *mpt)
        status = lambda args: json.loads(self.call("status", str(path), "--json", *args)[1])[0]["status"]
        (self.env.home / "resource" / "fonts" / "BeVietnamPro-Bold.ttf").write_bytes(b"a newer version of the font")
        self.assertEqual(status(mpt), "stale")
        self.assertEqual(self.call("qa", str(path), *mpt)[0], 1)
        self.assertEqual(status(no_mpt), "done")

    def test_run_exits_3_while_another_run_holds_the_batch(self):
        path = write_pack(self.root, [video()])
        mpt = ["--out", str(self.out), "--mpt-home", str(self.env.home), "--mpt-python", sys.executable]
        with runner.batch_lock(self.out / "test-batch"):
            code, _, err = self.call("run", str(path), *mpt)
            self.assertEqual(code, 3)
            self.assertIn("another", err)
            self.assertEqual(self.call("qa", str(path), *mpt)[0], 3)
            self.assertIn(self.call("status", str(path), "--json", *mpt)[0], (0, 1))  # status only reads
        self.assertEqual(self.call("run", str(path), *mpt)[0], 0)

    def _alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _interrupt_a_running_cli(self, sig):
        """Start the CLI as a real process against an MPT that never finishes, send it `sig`, and return the pid of that MPT."""
        (self.env.home / "cli.py").write_text("import os, sys, time\nopen('mpt.pid', 'w').write(str(os.getpid()))\ntime.sleep(120)\n")
        pidfile = self.env.home / "mpt.pid"
        path = write_pack(self.root, [video()])
        main = Path(__file__).resolve().parents[1] / "scripts" / "autovideo" / "main.py"
        cli_process = subprocess.Popen(
            [sys.executable, "-I", str(main), "run", str(path), "--out", str(self.out), "--mpt-home", str(self.env.home),
             "--mpt-python", sys.executable, "--retries", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pid = None
        try:
            for _ in range(300):  # the child is up when it has written its pid
                if pidfile.exists() and pidfile.read_text():
                    pid = int(pidfile.read_text())
                    break
                time.sleep(0.1)
            self.assertIsNotNone(pid, "the fake MPT never started")
            cli_process.send_signal(sig)
            cli_process.wait(timeout=30)
            for _ in range(50):  # the kill is sent before the CLI exits, but give the system a moment to reap
                if not self._alive(pid):
                    break
                time.sleep(0.1)
            return pid
        finally:
            if cli_process.poll() is None:
                cli_process.kill()
            if pid and self._alive(pid):
                os.kill(pid, signal.SIGKILL)  # never leave the fake MPT behind, whatever the test found

    def test_ctrl_c_stops_mpt_too(self):
        pid = self._interrupt_a_running_cli(signal.SIGINT)
        self.assertFalse(self._alive(pid), "MPT went on rendering after Ctrl-C")

    def test_sigterm_stops_mpt_too(self):
        pid = self._interrupt_a_running_cli(signal.SIGTERM)
        self.assertFalse(self._alive(pid), "MPT went on rendering after SIGTERM")
        with runner.batch_lock(self.out / "test-batch"):  # and the batch is free for the next run
            pass

    def test_doctor_never_prints_a_key(self):
        code, out, err = self.call("doctor", "--mpt-home", str(self.env.home), "--mpt-python", sys.executable)
        self.assertEqual(code, 0)
        self.assertIn("pexels_api_keys: set", out)
        self.assertNotIn(SECRET, out + err)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class QaTests(unittest.TestCase):
    def test_a_cue_that_runs_past_the_video_fails_even_when_it_is_not_the_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3:r=10", "-f", "lavfi",
                            "-i", "sine=frequency=300:sample_rate=22050", "-t", "3", "-pix_fmt", "yuv420p", str(media)], check=True)
            job = packmod.load_pack(write_pack(Path(tmp), [video()])).jobs[0]
            cues = [transcript.Cue(0.0, 100.0, "Xin chào các bạn"), transcript.Cue(1.0, 2.0, "hôm nay mình học")]  # starts are in order
            checks = {c.name: c for c in qa.check_video(job, media, None, cues)}
            self.assertFalse(checks["subtitle_inside_video"].ok)
            self.assertIn("100.0", checks["subtitle_inside_video"].detail)

    def test_a_voiced_job_must_come_with_its_narration_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3:r=10", "-f", "lavfi",
                            "-i", "sine=frequency=300:sample_rate=22050", "-t", "3", "-pix_fmt", "yuv420p", str(media)], check=True)  # sound: the music
            voiced = packmod.load_pack(write_pack(Path(tmp), [video(subtitles=False)])).jobs[0]  # default voice, music on
            checks = {c.name: c for c in qa.check_video(voiced, media, None, [])}
            self.assertFalse(checks["narration_made"].ok)  # the music alone makes it audible, which is not what was asked for
            self.assertTrue(checks["audible"].ok)
            speech = Path(tmp) / "narration.mp3"
            speech.write_bytes(media.read_bytes())  # any readable audio will do for this check
            self.assertTrue({c.name: c for c in qa.check_video(voiced, media, speech, [])}["narration_made"].ok)
            silent = packmod.load_pack(write_pack(Path(tmp), [video(voice="no-voice", subtitles=False)])).jobs[0]
            self.assertNotIn("narration_made", {c.name for c in qa.check_video(silent, media, None, [])})  # no-voice has none to make

    def test_overlapping_subtitle_cues_fail_the_order_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3:r=10", "-f", "lavfi",
                            "-i", "sine=frequency=300:sample_rate=22050", "-t", "3", "-pix_fmt", "yuv420p", str(media)], check=True)
            job = packmod.load_pack(write_pack(Path(tmp), [video()])).jobs[0]
            order = lambda cues: next(c for c in qa.check_video(job, media, None, cues) if c.name == "subtitle_order")
            cue = transcript.Cue
            self.assertFalse(order([cue(0.0, 2.5, "Xin chào các bạn"), cue(1.0, 2.9, "hôm nay mình học")]).ok)  # starts rise, the cues overlap
            self.assertTrue(order([cue(0.0, 1.5, "Xin chào các bạn"), cue(1.5, 2.9, "hôm nay mình học")]).ok)  # touching is fine
            self.assertTrue(order([cue(0.0, 1.5, "Xin chào các bạn"), cue(1.45, 2.9, "hôm nay mình học")]).ok)  # rounding noise is fine

    def test_no_voice_and_silent_music_expects_no_sound(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3:r=10", "-f", "lavfi",
                            "-i", "anullsrc=r=22050:cl=mono", "-t", "3", "-pix_fmt", "yuv420p", str(media)], check=True)  # a silent track, as MPT makes for no-voice
            silent = packmod.load_pack(write_pack(Path(tmp), [video(voice="no-voice", bgm="random", bgm_volume=0, subtitles=False)])).jobs[0]
            self.assertTrue(qa.passed(qa.check_video(silent, media, None, [])))  # asked for a silent video, got one
            music = packmod.load_pack(write_pack(Path(tmp), [video(voice="no-voice", bgm="random", bgm_volume=0.2, subtitles=False)])).jobs[0]
            failed = [c.name for c in qa.check_video(music, media, None, []) if not c.ok]
            self.assertIn("audible", failed)  # with the music on, silence is a defect

    def test_a_no_voice_video_with_subtitles_on_must_have_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=108x192:d=3:r=10", "-f", "lavfi",
                            "-i", "anullsrc=r=22050:cl=mono", "-t", "3", "-pix_fmt", "yuv420p", str(media)], check=True)
            make = lambda **d: packmod.load_pack(write_pack(Path(tmp), [video(voice="no-voice", bgm="none", **d)])).jobs[0]
            checks = {c.name: c for c in qa.check_video(make(subtitles=True), media, None, [])}  # MPT gives no-voice subtitles when asked
            self.assertFalse(checks["subtitles_made"].ok)
            self.assertNotIn("subtitles_made", {c.name for c in qa.check_video(make(subtitles=False), media, None, [])})

    def test_unreadable_file_fails_first_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "video.mp4"
            bad.write_bytes(b"not a video")
            job = packmod.load_pack(write_pack(Path(tmp), [video()])).jobs[0]
            checks = qa.check_video(job, bad, None, [])
            self.assertEqual([c.name for c in checks], ["readable"])
            self.assertFalse(qa.passed(checks))


if __name__ == "__main__":
    unittest.main()
