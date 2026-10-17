"""scripts/team/video/video_gates.py: the verdict on a rendered video's picture and sound.

The parsers and `evaluate` are pure and run on ffmpeg's real output, kept here as
text. The end-to-end tests render tiny clips with the host's ffmpeg and skip where
there is none. See docs/vps-team-video.md.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES_PATH = ROOT / "scripts" / "team" / "video" / "video_gates.py"


def load_module(name: str, path: Path):
    """Load from source, never from the bytecode cache (see test_session_budget)."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


gates = load_module("video_gates", GATES_PATH)

EBUR128 = """[Parsed_ebur128_0 @ 0x564436228680] Summary:

  Integrated loudness:
    I:         -32.9 LUFS
    Threshold: -43.3 LUFS

  Loudness range:
    LRA:        10.1 LU

  True peak:
    Peak:      -28.1 dBFS
"""
SILENCE = """size=       0kB time=00:00:00.00 bitrate=N/A speed=   0x    [silencedetect @ 0x55] silence_start: 0.999955
[silencedetect @ 0x55] silence_end: 6.01397 | silence_duration: 5.01401
[silencedetect @ 0x55] silence_start: 8.5
"""
EXPECT = {"duration_s": 6, "width": 640, "height": 360, "fps": 25}


def info(duration=6.0, audio=True, width=640, height=360, rate="25/1", audio_duration=None, video_duration=None,
         audio_start=None, format_start=None):
    streams = [{"codec_type": "video", "width": width, "height": height, "avg_frame_rate": rate,
                "duration": str(video_duration or duration)}]
    if audio:
        streams.append({"codec_type": "audio", "duration": str(audio_duration or duration)})
        if audio_start is not None:
            streams[-1]["start_time"] = str(audio_start)
    container = {"duration": str(duration)}
    if format_start is not None:
        container["start_time"] = str(format_start)
    return {"streams": streams, "format": container}


def failed(checks):
    return sorted(name for ok, name, _ in checks if not ok)


class ParserTests(unittest.TestCase):
    def test_loudness_is_read_from_the_ebur128_summary(self):
        self.assertEqual(gates.parse_loudness(EBUR128), (-32.9, -28.1))

    def test_digital_silence_reads_as_minus_infinity(self):
        text = EBUR128.replace("-28.1", "-inf")
        self.assertEqual(gates.parse_loudness(text)[1], float("-inf"))

    def test_a_missing_summary_is_unmeasured_not_zero(self):
        self.assertEqual(gates.parse_loudness("nothing here"), (None, None))

    def test_a_silence_that_never_ends_runs_to_the_end_of_the_audio(self):
        gaps, trailing = gates.parse_silences(SILENCE, audio_length=12.0)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0], 5.01401, places=3)
        self.assertAlmostEqual(trailing, 3.5, places=3)

    def test_a_silence_ffmpeg_closes_at_the_end_of_the_stream_is_the_trailing_one(self):
        # Codex's twelfth review: newer ffmpeg ends a trailing silence with a silence_end at the stream's last frame,
        # so it must not be filed with the silences inside the audio.
        closed = ("[silencedetect @ 0x1] silence_start: 5.0\n"
                  "[silencedetect @ 0x1] silence_end: 8.99 | silence_duration: 3.99\n"
                  "[silencedetect @ 0x1] silence_start: 1.0\n[silencedetect @ 0x1] silence_end: 2.5 | silence_duration: 1.5\n")
        gaps, trailing = gates.parse_silences(closed, audio_length=9.0)
        self.assertEqual([round(g, 2) for g in gaps], [1.5])
        self.assertAlmostEqual(trailing, 4.0, places=2)
        self.assertEqual(gates.parse_silences("", audio_length=9.0), ([], 0.0))

    def test_silencedetect_times_are_on_the_container_timeline_when_the_audio_starts_late(self):
        # Codex's twenty-first review. Real ffmpeg output for 15 s of audio that starts 2.476 s into a 20 s video: the tone
        # is silent for its first second and for its last 3 s. The times already include the 2.476 s, so a stream that
        # ends at 17.5 on the container's clock was compared with a bare length of 15.02.
        real = ("[silencedetect @ 0x55] silence_start: 2.47601\n"
                "[silencedetect @ 0x55] silence_end: 3.49925 | silence_duration: 1.02324\n"
                "[silencedetect @ 0x55] silence_start: 14.4992\n"
                "[silencedetect @ 0x55] silence_end: 17.4993 | silence_duration: 3.00009\n")
        gaps, trailing = gates.parse_silences(real, audio_length=15.02, audio_start=2.476)
        self.assertAlmostEqual(trailing, 3.0, places=2)
        # The first silence begins where the audio begins, so the 2.476 s before it belong to the same stretch of nothing.
        self.assertEqual([round(g, 2) for g in gaps], [3.5])

    def test_audio_that_is_silent_throughout_and_starts_late_is_one_silence_with_the_lead(self):
        gaps, trailing = gates.parse_silences("[silencedetect @ 0x1] silence_start: 3.0\n", audio_length=10.0, audio_start=3.0)
        self.assertEqual(gaps, [])
        self.assertAlmostEqual(trailing, 13.0, places=3)
        closed = "[silencedetect @ 0x1] silence_start: 3.0\n[silencedetect @ 0x1] silence_end: 13.0 | silence_duration: 10.0\n"
        gaps, trailing = gates.parse_silences(closed, audio_length=10.0, audio_start=3.0)
        self.assertEqual(gaps, [])
        self.assertAlmostEqual(trailing, 13.0, places=3)

    def test_the_audio_window_is_read_on_the_containers_clock(self):
        stream = {"codec_type": "audio", "start_time": "3.5", "duration": "15"}
        self.assertEqual(gates.audio_window({"streams": [stream], "format": {"duration": "20", "start_time": "1.0"}}, stream),
                         (2.5, 15.0))
        self.assertEqual(gates.audio_window({"streams": [], "format": {"duration": "20"}}, {"start_time": "N/A"}), (0.0, 20.0))
        early = {"start_time": "0.2"}
        self.assertEqual(gates.audio_window({"format": {"duration": "9", "start_time": "0.5"}}, early), (0.0, 9.0))


class FrameRateTests(unittest.TestCase):
    def test_fractions_whole_numbers_and_unknowns(self):
        rate = lambda text: gates.frame_rate({"avg_frame_rate": text})  # noqa: E731
        self.assertAlmostEqual(rate("30000/1001"), 29.97, places=2)
        self.assertEqual(rate("25"), 25.0)
        for unknown in ("0/0", "N/A", ""):
            self.assertEqual(rate(unknown), 0.0, unknown)

    def test_an_unreadable_frame_rate_fails_the_fps_check_instead_of_crashing(self):
        checks = gates.evaluate(info(rate="N/A"), (-14.0, -3.0), [], EXPECT)
        self.assertEqual(failed(checks), ["fps"])


class EvaluateTests(unittest.TestCase):
    GOOD = (-14.0, -3.0)

    def run_checks(self, media=None, loudness=GOOD, gaps=(), expected=None, trailing=0.0):
        return gates.evaluate(media or info(), loudness, list(gaps), expected or EXPECT, trailing)

    def test_a_matching_video_with_sound_passes_every_check(self):
        self.assertEqual(failed(self.run_checks()), [])

    def test_a_render_without_an_audio_stream_fails(self):
        self.assertIn("audio stream", failed(self.run_checks(info(audio=False), loudness=None)))

    def test_audio_can_be_declared_optional(self):
        expected = {**EXPECT, "audio": {"required": False}}
        self.assertEqual(failed(self.run_checks(info(audio=False), loudness=None, expected=expected)), [])

    def test_a_silent_track_fails_on_loudness(self):
        self.assertIn("loudness", failed(self.run_checks(loudness=(-70.0, float("-inf")))))

    def test_clipping_fails_on_true_peak(self):
        self.assertEqual(failed(self.run_checks(loudness=(-14.0, 0.5))), ["true peak"])

    def test_an_unmeasured_loudness_fails_instead_of_passing_silently(self):
        self.assertEqual(failed(self.run_checks(loudness=(None, None))), ["loudness", "true peak"])

    def test_a_long_silence_fails(self):
        self.assertEqual(failed(self.run_checks(gaps=[1.0, 4.5])), ["silence gap"])

    def test_a_silent_tail_after_the_audio_stream_ends_counts_as_silence(self):
        # Codex's seventh review: silencedetect only sees the audio stream, so the stretch between its end and the end of the
        # video was never counted. 45 s of sound in a 50 s video passes the 90% coverage check but ends in 5 s of nothing.
        checks = self.run_checks(info(duration=50.0, audio_duration=45.0), expected={**EXPECT, "duration_s": 50})
        self.assertEqual(failed(checks), ["silence gap"])
        detail = next(text for ok, name, text in checks if name == "silence gap")
        self.assertIn("5.0s", detail)

    def test_trailing_silence_and_the_missing_audio_tail_are_one_silence(self):
        # Codex's twelfth review: 4 s of silence at the end of a 9 s audio stream, in a 10 s video, is 5 s of nothing, not
        # the larger of 4 and 1.
        media, expected = info(duration=10.0, audio_duration=9.0), {**EXPECT, "duration_s": 10}
        checks = self.run_checks(media, expected=expected, trailing=4.0)
        self.assertEqual(failed(checks), ["silence gap"])
        self.assertIn("5.0s", next(text for ok, name, text in checks if name == "silence gap"))
        self.assertEqual(failed(self.run_checks(media, expected=expected, trailing=2.0)), [], "3 s in all")
        self.assertEqual(failed(self.run_checks(media, expected=expected, trailing=0.0)), [])

    def test_the_tail_does_not_add_to_a_silence_inside_the_audio(self):
        media, expected = info(duration=10.0, audio_duration=9.0), {**EXPECT, "duration_s": 10}
        self.assertEqual(failed(self.run_checks(media, expected=expected, gaps=[3.5])), [], "an inner pause and a 1 s tail")

    def test_a_late_start_and_an_early_end_are_two_silences_not_one(self):
        # Codex's twenty-first review: audio that runs from 2.5 s to 47.5 s of a 50 s video is 90% of it, with a 2.5 s gap at
        # each end. They are not adjacent, so the longest silence is 2.5 s, not their sum.
        media = info(duration=50.0, audio_duration=45.0, audio_start=2.5)
        self.assertEqual(failed(self.run_checks(media, expected={**EXPECT, "duration_s": 50})), [])

    def test_a_late_start_alone_counts_as_silence_before_the_sound(self):
        media = info(duration=50.0, audio_duration=45.0, audio_start=5.0)
        checks = self.run_checks(media, expected={**EXPECT, "duration_s": 50})
        self.assertEqual(failed(checks), ["silence gap"])
        self.assertIn("5.0s", next(text for ok, name, text in checks if name == "silence gap"))

    def test_the_late_start_is_measured_from_the_containers_first_timestamp(self):
        media = info(duration=50.0, audio_duration=45.0, audio_start=6.0, format_start=3.0)
        self.assertEqual(failed(self.run_checks(media, expected={**EXPECT, "duration_s": 50})), [])

    def test_a_short_tail_within_the_limit_is_fine(self):
        checks = self.run_checks(info(duration=50.0, audio_duration=47.0), expected={**EXPECT, "duration_s": 50})
        self.assertEqual(failed(checks), [])

    def test_a_short_audio_track_fails_on_coverage(self):
        self.assertEqual(failed(self.run_checks(info(audio_duration=3.0))), ["audio coverage"])

    def test_a_wrong_length_fails_on_duration(self):
        self.assertEqual(failed(self.run_checks(info(duration=9.0))), ["duration", "video duration"])

    def test_a_picture_that_stops_before_the_sound_fails_on_video_duration(self):
        # Codex's tenth review: 2 s of picture plus 6 s of sound reads 6 s on the container, so every other check passed
        # while the player froze on the last frame.
        checks = self.run_checks(info(video_duration=2.0))
        self.assertEqual(failed(checks), ["video duration"])
        self.assertIn("2.00s", next(text for ok, name, text in checks if name == "video duration"))

    def test_a_video_stream_that_reports_no_duration_is_unmeasured_not_passed(self):
        media = info()
        media["streams"][0].pop("duration")
        checks = self.run_checks(media)
        self.assertEqual(failed(checks), ["video duration"])
        self.assertIn("unmeasured", next(text for ok, name, text in checks if name == "video duration"))
        media["streams"][0]["duration"] = "N/A"
        self.assertEqual(failed(self.run_checks(media)), ["video duration"])

    def test_the_duration_tolerance_is_honoured(self):
        expected = {**EXPECT, "duration_tolerance_s": 5}
        self.assertEqual(failed(self.run_checks(info(duration=9.0), expected=expected)), [])

    def test_wrong_size_and_frame_rate_fail(self):
        media = info(width=1280, height=720, rate="30000/1001")
        self.assertEqual(failed(self.run_checks(media)), ["fps", "height", "width"])

    def test_the_loudness_window_comes_from_expected_json(self):
        expected = {**EXPECT, "audio": {"lufs_min": -20, "lufs_max": -16}}
        self.assertEqual(failed(self.run_checks(loudness=(-14.0, -3.0), expected=expected)), ["loudness"])


class ExpectedFileTests(unittest.TestCase):
    def write(self, data) -> Path:
        path = Path(tempfile.mkdtemp()) / "expected.json"
        self.addCleanup(shutil.rmtree, path.parent, True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_a_typo_in_a_key_is_an_error_not_a_disabled_check(self):
        with self.assertRaises(SystemExit) as raised:
            gates.load_expected(self.write({"duration_s": 6, "audio": {"lufs_mn": -20}}))
        self.assertIn("audio.lufs_mn", str(raised.exception))

    def test_duration_is_required(self):
        with self.assertRaises(SystemExit):
            gates.load_expected(self.write({"width": 640}))

    def test_a_string_where_a_number_belongs_is_a_clean_error(self):
        for data in ({"duration_s": 6, "fps": "30"}, {"duration_s": 6, "audio": {"lufs_min": "-20"}},
                     {"duration_s": True}, {"duration_s": 6, "width": False}):
            with self.subTest(data=data):
                with self.assertRaises(SystemExit) as raised:
                    gates.load_expected(self.write(data))
                self.assertIn("must be", str(raised.exception))

    def test_audio_required_must_be_true_or_false(self):
        with self.assertRaises(SystemExit) as raised:
            gates.load_expected(self.write({"duration_s": 6, "audio": {"required": "no"}}))
        self.assertIn("audio.required", str(raised.exception))
        self.assertEqual(gates.load_expected(self.write({"duration_s": 6, "audio": {"required": False}}))["audio"],
                         {"required": False})

    def test_a_valid_file_loads(self):
        self.assertEqual(gates.load_expected(self.write(EXPECT)), EXPECT)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg and ffprobe")
class RenderedClipTests(unittest.TestCase):
    """The same verdicts, on real files."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)
        picture = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=4"]
        encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        sound = ["-c:a", "aac", "-shortest"]

        def make(name, *inputs):
            subprocess.run(["ffmpeg", "-v", "error", "-y", *picture, *inputs, *encode, str(cls.dir / name)], check=True)

        make("good.mp4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4,volume=3", *sound)
        make("noaudio.mp4")
        make("silent.mp4", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=4", *sound)
        # 1.5 s of picture under 4 s of sound: the container says 4 s, the picture stream says 1.5 s.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=1.5",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4,volume=3", *encode, "-c:a", "aac",
                        str(cls.dir / "short-picture.mp4")], check=True)
        # 1.5 s of sound, 2.5 s of digital silence, then the audio stream ends two seconds before the picture does.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=6",
                        "-f", "lavfi", "-i", "aevalsrc=if(lt(t\\,1.5)\\,0.2*sin(2*PI*440*t)\\,0):d=4:s=44100", *encode,
                        "-c:a", "aac", str(cls.dir / "dead-ending.mp4")], check=True)
        # 7 s of sound that starts 2.5 s into 12 s of picture: a 2.5 s gap at each end.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=12",
                        "-itsoffset", "2.5", "-f", "lavfi", "-i", "sine=frequency=440:duration=7,volume=3", *encode,
                        "-c:a", "aac", str(cls.dir / "both-ends.mp4")], check=True)
        # The same, but the sound is silent for its first 2 s: 2.5 s of nothing before it plus 2 s inside it.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=12",
                        "-itsoffset", "2.5", "-f", "lavfi", "-i", "aevalsrc=if(lt(t\\,2)\\,0\\,0.2*sin(2*PI*440*t)):d=9:s=44100",
                        *encode, "-c:a", "aac", str(cls.dir / "late-and-quiet.mp4")], check=True)
        cls.expect_late = cls.dir / "expected-late.json"
        cls.expect_late.write_text(json.dumps({"duration_s": 12, "width": 640, "height": 360, "fps": 25,
                                               "audio": {"min_coverage": 0.5}}))
        cls.expect_dead = cls.dir / "expected-dead.json"
        cls.expect_dead.write_text(json.dumps({"duration_s": 6, "width": 640, "height": 360, "fps": 25,
                                               "audio": {"min_coverage": 0.5}}))
        cls.expect = cls.dir / "expected.json"
        cls.expect.write_text(json.dumps({"duration_s": 4, "width": 640, "height": 360, "fps": 25}))

    def verdict(self, name, expect=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates.main([str(self.dir / name), "--expect", str(expect or self.expect)])
        return code, json.loads(out.getvalue().splitlines()[-1])

    def test_a_clip_with_sound_passes(self):
        code, summary = self.verdict("good.mp4")
        self.assertEqual((code, summary["failed"]), (0, []))

    def test_a_clip_without_an_audio_stream_is_rejected(self):
        code, summary = self.verdict("noaudio.mp4")
        self.assertEqual((code, summary["failed"]), (1, ["audio stream"]))

    def test_a_clip_with_only_silence_is_rejected(self):
        code, summary = self.verdict("silent.mp4")
        self.assertEqual(code, 1)
        self.assertIn("loudness", summary["failed"])

    def test_a_picture_that_ends_before_the_sound_is_rejected(self):
        code, summary = self.verdict("short-picture.mp4")
        self.assertEqual((code, summary["failed"]), (1, ["video duration"]))

    def test_silence_at_the_end_of_a_short_audio_stream_adds_to_the_missing_tail(self):
        # 2.5 s of silence inside the audio stream plus 2 s with no audio at all: neither passes the 4 s limit alone.
        code, summary = self.verdict("dead-ending.mp4", self.expect_dead)
        self.assertEqual((code, summary["failed"]), (1, ["silence gap"]))

    def test_a_gap_at_each_end_of_the_audio_is_not_one_gap(self):
        # Codex's twenty-first review: 2.5 s before the sound and 2.5 s after it are separate silences.
        code, summary = self.verdict("both-ends.mp4", self.expect_late)
        self.assertEqual((code, summary["failed"]), (0, []))

    def test_silence_before_a_late_stream_adds_to_a_silence_that_starts_with_it(self):
        code, summary = self.verdict("late-and-quiet.mp4", self.expect_late)
        self.assertEqual((code, summary["failed"]), (1, ["silence gap"]))

    def test_a_missing_render_is_rejected(self):
        code, summary = self.verdict("never-rendered.mp4")
        self.assertEqual((code, summary["failed"]), (1, ["render"]))


if __name__ == "__main__":
    unittest.main()
