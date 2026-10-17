"""Tests for the radar-digest-to-video scripts: no network, no model, no browser.

    python3 -m unittest discover -s tests -v

Fixtures are real digests (draft-vi.json) copied from the github-radar repository: a typical one (voicestudio), one without try_it
(moneyprinterturbo), one whose problem is a single sentence (orca) and the longest one (impeccable).
"""
import copy
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "radar"))
sys.path.insert(0, str(REPO / "scripts" / "vo"))

import check_facts  # noqa: E402
import compose  # noqa: E402
import make_video  # noqa: E402
import numbers_vi  # noqa: E402
import plan as planlib  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
NAMES = ["voicestudio", "moneyprinterturbo", "orca", "impeccable"]


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def estimated_durations(plan):
    return {u["id"]: u["est"] for u in plan["units"]}


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.audio = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "audio":
            self.audio[attrs["id"]] = attrs


def run_gate(digest, doc, html, files=None):
    """check_facts.py as a subprocess, the way make_video.py runs it. Returns (exit status, output). The page gets the template's
    gsap.min.js next to it, as a project has, unless `files` ({name: text}) puts something else there."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "gsap.min.js").write_bytes((REPO / "scripts" / "radar" / "assets" / "gsap.min.js").read_bytes())
        for name, text in (files or {}).items():
            (tmp / name).write_text(text, encoding="utf-8")
        (tmp / "draft.json").write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
        (tmp / "lines.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        (tmp / "index.html").write_text(html, encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "vo" / "check_facts.py"), "--source", str(tmp / "draft.json"),
                                 "--lines", str(tmp / "lines.json"), "--html", str(tmp / "index.html")], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


class NumberWords(unittest.TestCase):
    def test_integers(self):
        expected = {0: "không", 5: "năm", 10: "mười", 11: "mười một", 15: "mười lăm", 21: "hai mươi mốt", 25: "hai mươi lăm",
                    101: "một trăm lẻ một", 110: "một trăm mười", 646: "sáu trăm bốn mươi sáu", 1001: "một nghìn không trăm lẻ một",
                    62958: "sáu mươi hai nghìn chín trăm năm mươi tám", 1000000: "một triệu"}
        for number, words in expected.items():
            self.assertEqual(numbers_vi.integer_words(number), words, number)

    def test_text(self):
        self.assertEqual(numbers_vi.speak_text("62.958 sao"), "sáu mươi hai nghìn chín trăm năm mươi tám sao")
        self.assertEqual(numbers_vi.speak_text("khoảng 5 GB"), "khoảng năm GB")
        self.assertEqual(numbers_vi.speak_text("giảm 50%"), "giảm năm mươi phần trăm")
        self.assertEqual(numbers_vi.speak_text("3,5 và 3.14"), "ba phẩy năm và ba chấm một bốn")

    def test_digits_that_belong_to_a_name_stay(self):
        for text in ("MP4", "Qwen3", "v1.2.3", "ngày 2026-10-13", "gpt-4o", "1.5x", "H.264"):
            self.assertEqual(numbers_vi.speak_text(text), text)

    def test_the_version_of_a_license_name_is_read(self):
        self.assertEqual(numbers_vi.speak_text("giấy phép AGPL-3.0, nhưng"), "giấy phép AGPL ba chấm không, nhưng")
        self.assertEqual(numbers_vi.speak_text("Apache-2.0"), "Apache hai chấm không")


class Sentences(unittest.TestCase):
    def test_split_on_capitals_only(self):
        self.assertEqual(planlib.split_sentences("Một ý. Hai ý! Ba ý?"), ["Một ý.", "Hai ý!", "Ba ý?"])
        self.assertEqual(planlib.split_sentences("Dùng AGPL-3.0. nhưng v2.1 vẫn đúng."), ["Dùng AGPL-3.0. nhưng v2.1 vẫn đúng."])

    def test_backticks_are_dropped(self):
        self.assertEqual(planlib.clean("chạy `init`  rồi\n`npx x`"), "chạy init rồi npx x")


class Plan(unittest.TestCase):
    def test_every_fixture_plans(self):
        for name in NAMES:
            plan = planlib.build_plan(planlib.load_digest(FIXTURES / f"{name}.json"))
            kinds = [u["key"].split(":")[0] for u in plan["units"]]
            self.assertEqual(kinds[0], "hook", name)
            self.assertIn("problem", kinds, name)
            self.assertGreaterEqual(kinds.count("step"), 3, name)
            self.assertEqual([u["id"] for u in plan["units"]], [f"vo-{i}" for i in range(1, len(plan["units"]) + 1)])

    def test_narration_is_the_digests_own_text(self):
        for name in NAMES:
            digest = planlib.load_digest(FIXTURES / f"{name}.json")
            draft = digest["draft"]
            pool = " ".join(planlib.clean(json.dumps(draft, ensure_ascii=False).replace("\\n", " ")).split())
            for unit in planlib.build_plan(digest)["units"]:
                text = unit["text"].split(". ", 1)[1] if unit["key"] == "hook" else unit["text"]
                self.assertIn(text.replace("`", ""), pool.replace("`", ""), f"{name} {unit['key']}")

    def test_budget_cuts_in_order(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        roomy = planlib.build_plan(digest, speech_seconds=500)
        tight = planlib.build_plan(digest, speech_seconds=10)
        keys = lambda p: [u["key"] for u in p["units"]]  # noqa: E731
        self.assertGreater(len(roomy["units"]), len(tight["units"]))
        self.assertIn("try", keys(roomy))
        self.assertNotIn("try", keys(tight))
        self.assertEqual(sum(k.startswith("step") for k in keys(tight)), 3)
        self.assertEqual(sum(k.startswith("caveat") for k in keys(tight)), 1)
        self.assertEqual(sum(k.startswith("learn") for k in keys(tight)), 2)
        self.assertIn("over the speech budget", tight["note"])
        self.assertIsNone(roomy["note"])

    def test_the_solution_is_the_sentence_that_names_the_tool(self):
        digest = planlib.load_digest(FIXTURES / "impeccable.json")
        plan = planlib.build_plan(digest)
        self.assertTrue(plan["problem"][-1]["text"].startswith("Impeccable thêm"), plan["problem"][-1]["text"])

    def test_single_sentence_problem(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "orca.json"))
        self.assertEqual(len(plan["problem"]), 1)

    def test_selection_reproduces_the_plan(self):
        digest = planlib.load_digest(FIXTURES / "moneyprinterturbo.json")
        first = planlib.build_plan(digest)
        again = planlib.build_plan(digest, selection=[u["key"] for u in first["units"]])
        self.assertEqual(first["units"], again["units"])
        with self.assertRaises(ValueError):
            planlib.build_plan(digest, selection=["hook", "step:99"])

    def test_chips_come_from_the_facts(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        self.assertEqual([c["value"] for c in plan["chips"]], ["62.958", "7.006", "AGPL-3.0", "Python"])
        self.assertEqual(plan["url_text"], "github.com/debpalash/VoiceStudio")

    def test_rejects_other_languages_and_broken_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            for label, change in (("en", lambda d: d.update(lang="en")), ("no title", lambda d: d["draft"].pop("title")),
                                  ("no repo", lambda d: d["facts"].update(full_name="x"))):
                digest = fixture("voicestudio")
                change(digest)
                path = Path(tmp) / f"{label}.json"
                path.write_text(json.dumps(digest), encoding="utf-8")
                with self.assertRaises(ValueError, msg=label):
                    planlib.load_digest(path)


class Timeline(unittest.TestCase):
    def test_clips_sit_inside_their_scenes_in_order(self):
        for name in NAMES:
            plan = planlib.build_plan(planlib.load_digest(FIXTURES / f"{name}.json"))
            tl = planlib.timeline(plan, estimated_durations(plan))
            previous_end = 0.0
            for scene, members in zip(tl["scenes"], plan["scenes"]):
                self.assertAlmostEqual(scene["start"], previous_end, places=2, msg=name)
                last = 0.0
                for uid in members["units"]:
                    clip = tl["clips"][uid]
                    self.assertGreaterEqual(clip["start"], max(scene["start"] + planlib.LEAD - 0.01, last), name)
                    self.assertLessEqual(clip["end"] + planlib.TAIL - 0.01, scene["end"], name)
                    last = clip["end"]
                previous_end = scene["end"]
            self.assertAlmostEqual(tl["duration"], previous_end, places=2)

    def test_terminal_without_a_note_gets_time_to_type(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        self.assertTrue(plan["try"]["commands"] and not plan["try"]["uid"])
        tl = planlib.timeline(plan, estimated_durations(plan))
        end_scene = tl["scenes"][-1]
        done = planlib.terminal_done_at(plan, tl["clips"], end_scene["start"])
        self.assertGreaterEqual(end_scene["end"], done + planlib.TERMINAL_HOLD - 0.01)


class Compose(unittest.TestCase):
    def build(self, name, speech_seconds=60.0):
        digest = planlib.load_digest(FIXTURES / f"{name}.json")
        plan = planlib.build_plan(digest, speech_seconds=speech_seconds)
        tl = planlib.timeline(plan, estimated_durations(plan))
        return digest, plan, tl, compose.render(plan, tl)

    def test_structure(self):
        for name in NAMES:
            _, plan, tl, html = self.build(name)
            ids = Ids()
            ids.feed(html)
            self.assertEqual(len(ids.ids), len(set(ids.ids)), f"{name}: duplicate ids")
            for unit in plan["units"]:
                tag = ids.audio[unit["id"]]
                self.assertAlmostEqual(float(tag["data-start"]), tl["clips"][unit["id"]]["start"], places=2, msg=name)
            self.assertIn("music-bed", ids.audio)
            self.assertIn(f'data-duration="{compose.num(tl["duration"])}"', html)
            self.assertIn('window.__timelines["main"] = tl;', html)
            for forbidden in ("Date.now", "Math.random", "fetch(", "http://", "https://"):
                self.assertNotIn(forbidden, html, f"{name}: {forbidden}")

    def test_the_composition_says_only_what_the_digest_says(self):
        for name in NAMES:
            digest, plan, tl, html = self.build(name)
            doc = make_video.voiceover_doc(plan, tl)
            status, output = run_gate(digest, doc, html)
            self.assertEqual(status, 0, f"{name}: {output}")

    def test_the_gate_catches_an_invented_number_on_screen(self):
        digest, plan, tl, _ = self.build("voicestudio")
        broken = copy.deepcopy(plan)
        broken["chips"][0]["value"] = "99.999"
        status, output = run_gate(digest, make_video.voiceover_doc(plan, tl), compose.render(broken, tl))
        self.assertEqual(status, 1)
        self.assertIn("99999", output)

    def test_fixed_labels_are_not_traced_but_digest_text_is(self):
        digest, plan, tl, html = self.build("voicestudio")
        self.assertIn("data-label", html)
        broken = copy.deepcopy(plan)
        broken["learn"][0]["text"] = "Dùng ElevenLabs để tăng tốc"
        status, output = run_gate(digest, make_video.voiceover_doc(plan, tl), compose.render(broken, tl))
        self.assertEqual(status, 1)
        self.assertIn("ElevenLabs", output)

    def test_text_is_escaped(self):
        digest, plan, tl, _ = self.build("voicestudio")
        broken = copy.deepcopy(plan)
        broken["subtitle"] = "<script>alert(1)</script> & co"
        html = compose.render(broken, tl)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", html)

    def test_scenes_that_have_no_content_are_left_out(self):
        digest = fixture("voicestudio")
        digest["draft"]["learn"] = []
        digest["draft"]["caveats"] = []
        digest["draft"].pop("try_it")
        digest["draft"]["how_it_works"]["components"] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            path.write_text(json.dumps(digest), encoding="utf-8")
            plan = planlib.build_plan(planlib.load_digest(path))
        self.assertEqual([s["id"] for s in plan["scenes"]], ["cover", "problem", "how"])
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        self.assertNotIn("Học được gì", html)
        self.assertNotIn("Các mảnh ghép", html)


def digest_with(change):
    """A copy of the voicestudio fixture changed by `change(digest)`, loaded the way a file would be."""
    digest = fixture("voicestudio")
    change(digest)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "d.json"
        path.write_text(json.dumps(digest), encoding="utf-8")
        return planlib.load_digest(path)


class ReviewFindings(unittest.TestCase):
    """Regression tests for the findings of the first review of the scripts."""

    def test_the_timelines_registry_is_created_before_it_is_used(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        html = compose.render(plan, planlib.timeline(plan, estimated_durations(plan)))
        init = html.index("window.__timelines = window.__timelines || {};")
        self.assertLess(init, html.index('window.__timelines["main"] = tl;'))

    def test_render_does_not_start_when_the_facts_gate_fails(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "source").mkdir()
            (project / "source" / "draft-vi.json").write_text(json.dumps(fixture("voicestudio")), encoding="utf-8")
            shutil.copyfile(REPO / "scripts" / "radar" / "assets" / "gsap.min.js", project / "gsap.min.js")     # what scaffold puts there
            make_video.write_composition(project, plan, tl)
            self.assertIn("all traced", make_video.require_gate(project))
            html = (project / "index.html").read_text(encoding="utf-8").replace(">Python<", ">Python 99.999<", 1)
            (project / "index.html").write_text(html, encoding="utf-8")
            with self.assertRaises(SystemExit):
                make_video.require_gate(project)

    def test_commands_with_nothing_to_narrate_still_get_their_scene(self):
        def change(d):
            d["draft"]["caveats"] = []
            d["draft"]["try_it"].pop("note")
        digest = digest_with(change)
        plan = planlib.build_plan(digest)
        self.assertEqual(plan["scenes"][-1], {"id": "end", "units": []})
        self.assertEqual(len(plan["try"]["commands"]), 3)
        tl = planlib.timeline(plan, estimated_durations(plan))
        scene = tl["scenes"][-1]
        self.assertEqual(scene["id"], "end")
        self.assertGreaterEqual(scene["end"], planlib.terminal_done_at(plan, tl["clips"], scene["start"]) + planlib.TERMINAL_HOLD - 0.01)
        html = compose.render(plan, tl)
        self.assertIn("bun run setup:api", html)
        doc = make_video.voiceover_doc(plan, tl)
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 0, output)

    def test_more_commands_than_the_terminal_shows(self):
        many = [f"bun run step{i}" for i in range(9)]
        digest = digest_with(lambda d: d["draft"]["try_it"].update(commands=many))
        plan = planlib.build_plan(digest)
        self.assertEqual(plan["try"]["commands"], many[:planlib.MAX_COMMANDS])
        self.assertIn("the first 6", plan["note"])
        tl = planlib.timeline(plan, estimated_durations(plan))
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(doc["commands_shown"], planlib.MAX_COMMANDS)
        html = compose.render(plan, tl)
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 0, output)
        end = tl["scenes"][-1]
        self.assertGreaterEqual(end["end"], planlib.terminal_done_at(plan, tl["clips"], end["start"]) + planlib.TERMINAL_HOLD - 0.01,
                                "the last command is typed and read before the scene ends")
        # the gate still refuses a terminal that drops a command it says it shows
        status, output = run_gate(digest, doc, html.replace("bun run step3", "bun run step"))
        self.assertEqual(status, 1)
        self.assertIn("step3", output)
        # and without the declaration every command of the digest is required
        del doc["commands_shown"]
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 1)
        self.assertIn("step7", output)


    def test_a_partial_redo_keeps_the_voice_of_the_project(self):
        doc, report = {"voice": "Mai Anh"}, {"voice": {"voice": "Hải Đăng"}}
        self.assertEqual(make_video.resolve_voice(None, doc, report, True), "Mai Anh")        # the project's own record wins
        self.assertEqual(make_video.resolve_voice(None, {}, report, True), "Hải Đăng")        # else the report's
        self.assertEqual(make_video.resolve_voice(None, {}, {}, True), make_video.DEFAULT_VOICE)
        self.assertEqual(make_video.resolve_voice(None, doc, report, False), "Mai Anh")       # a full redo keeps it too
        self.assertEqual(make_video.resolve_voice("Mai Anh", doc, report, True), "Mai Anh")
        self.assertEqual(make_video.resolve_voice("Thái Sơn", doc, report, False), "Thái Sơn")  # a full redo may change it
        with self.assertRaises(SystemExit):                                                    # a partial one may not: two narrators
            make_video.resolve_voice("Thái Sơn", doc, report, True)

    def test_the_recorded_voice_survives_rewriting_voiceover_json(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        tl = planlib.timeline(plan, estimated_durations(plan))
        doc = make_video.voiceover_doc(plan, tl)
        self.assertNotIn("voice", doc)
        doc["voice"] = "Mai Anh"
        self.assertEqual(make_video.voiceover_doc(plan, tl, doc)["voice"], "Mai Anh")


    def test_commands_shown_is_checked_not_trusted(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(doc["commands_shown"], 3)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        # a stale or edited 0, with the terminal's lines removed, must not slip through
        doc["commands_shown"] = 0
        bare = html
        for command in ("bun install", "bun run setup:api", "bun run dev"):
            bare = bare.replace(f">{command}<", "><")
        status, output = run_gate(digest, doc, bare)
        self.assertEqual(status, 1)
        self.assertIn("commands_shown is 0", output)
        # and one that is too large is refused as well
        doc["commands_shown"] = 9
        self.assertEqual(run_gate(digest, doc, html)[0], 1)

    def test_projects_with_the_same_name_in_different_folders_keep_separate_build_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            saved = make_video.BUILD
            make_video.BUILD = tmp / "build"
            try:
                a, b = tmp / "one" / "video", tmp / "two" / "video"
                a.mkdir(parents=True), b.mkdir(parents=True)
                self.assertNotEqual(make_video.build_dir(a), make_video.build_dir(b))
                make_video.save_report(a, {"voice": {"voice": "Mai Anh", "chosen": {"vo-1": {"take": 2}}}})
                make_video.save_report(b, {"voice": {"voice": "Thái Sơn", "chosen": {}}})
                self.assertEqual(make_video.load_report(a)["voice"]["voice"], "Mai Anh")     # not overwritten by the other project
                self.assertEqual(make_video.load_report(b)["voice"]["voice"], "Thái Sơn")
                make_video.reset_build(a)                                                     # a scaffold starts its own folder clean
                self.assertEqual(make_video.load_report(a), {})
                self.assertEqual(make_video.load_report(b)["voice"]["voice"], "Thái Sơn")
                self.assertEqual(make_video.build_dir(a), make_video.build_dir(a))            # stable for the same folder
            finally:
                make_video.BUILD = saved

    def test_the_readme_table_survives_pipes_and_line_breaks_in_a_line(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            (project / "source").mkdir(parents=True)
            doc = make_video.write_composition(project, plan, tl)
            doc["lines"][1]["text"] = "Dẫn kết quả qua cat a | grep b,\nrồi đếm."
            make_video.write_readme(project, plan, doc, {"voice": {"voice": "Hải Đăng"}, "render": {"duration": 60.0, "check": "ok"}})
            rows = [l for l in (project / "README.md").read_text(encoding="utf-8").splitlines() if l.startswith("| `vo-")]
        self.assertEqual(len(rows), len(doc["lines"]), "one table row per line")
        bad = next(r for r in rows if r.startswith("| `vo-2`"))
        self.assertIn("a \\| grep b, rồi đếm.", bad)
        self.assertEqual(bad.replace("\\|", "").count("|"), 6, "five cells, whatever the text says")


    def test_a_data_label_element_hides_nothing_but_the_fixed_labels(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        # an invented number or name placed in a data-label element is read like any other text
        for sneaky in ("Nhanh gấp 99999 lần", "Dùng ElevenLabs"):
            status, output = run_gate(digest, doc, html.replace('data-label>Tự thử<', f'data-label>{sneaky}<', 1))
            self.assertEqual(status, 1, sneaky)
        # the real label text may be replaced by another real label, and nothing else passes
        self.assertEqual(run_gate(digest, doc, html.replace('data-label>Tự thử<', 'data-label>Nó chạy như thế nào<', 1))[0], 0)
        # a label that wraps other elements cannot hide them either
        wrapped = html.replace('<div class="scan"', '<div data-label><b>Dùng ElevenLabs</b></div><div class="scan"', 1)
        self.assertEqual(run_gate(digest, doc, wrapped)[0], 1)

    def test_a_decimal_point_is_not_a_thousands_separator(self):
        self.assertEqual(check_facts.numbers("62.958 và 62,958"), {"62958"})
        self.assertEqual(check_facts.numbers("7.006"), {"7006"})
        self.assertEqual(check_facts.numbers("3.14 và 3,14"), {"3.14"})
        self.assertEqual(check_facts.numbers("2026-10-13"), {"2026", "10", "13"})
        source = check_facts.blob({"field": "pi là 3.14 và có 62958 sao"})
        self.assertEqual(check_facts.untraced("pi là 3.14, 62.958 sao", source, set()), [])
        self.assertEqual(check_facts.untraced("pi là 314", source, set()), ["number 314"])
        self.assertEqual(check_facts.untraced("có 6.2958 sao", source, set()), ["number 6.2958"])

    def test_a_minus_sign_is_part_of_the_value(self):
        self.assertEqual(check_facts.numbers("ngưỡng -19 dB và 19 dB"), {"-19", "19"})
        self.assertEqual(check_facts.numbers("ngưỡng −19 dB"), {"-19"})              # U+2212 is the same sign
        self.assertEqual(check_facts.numbers("(-0,5)"), {"-0.5"})
        # a hyphen inside a name, a date or a range is not a sign
        self.assertEqual(check_facts.numbers("AGPL-3.0, gpt-4o, 10-20, 2026-10-13"), {"3.0", "4", "10", "20", "2026", "13"})
        source = check_facts.blob({"field": "ngưỡng -19 dB, cao hơn -3.5 dB"})
        self.assertEqual(check_facts.untraced("ngưỡng -19 dB", source, set()), [])
        self.assertEqual(check_facts.untraced("ngưỡng 19 dB", source, set()), ["number 19"])       # the sign cannot be dropped
        self.assertEqual(check_facts.untraced("cao hơn 3.5 dB", source, set()), ["number 3.5"])
        positive = check_facts.blob({"field": "ngưỡng 19 dB"})
        self.assertEqual(check_facts.untraced("ngưỡng -19 dB", positive, set()), ["number -19"])   # nor added

    def test_a_negative_number_is_read_with_its_sign(self):
        self.assertEqual(numbers_vi.speak_text("ngưỡng -19 dB"), "ngưỡng âm mười chín dB")
        self.assertEqual(numbers_vi.speak_text("từ −3,5 đến 3,5"), "từ âm ba phẩy năm đến ba phẩy năm")
        self.assertEqual(numbers_vi.speak_text("giảm -20%"), "giảm âm hai mươi phần trăm")
        # hyphens that are not signs are left as before
        self.assertEqual(numbers_vi.speak_text("gpt-4o và 10-20"), "gpt-4o và 10-20")
        self.assertEqual(numbers_vi.speak_text("giấy phép AGPL-3.0"), "giấy phép AGPL ba chấm không")

    def test_the_reading_and_the_gate_agree_on_thousands(self):
        # the gate treats 62,958 like 62.958 (groups of exactly three digits), so the voice must read both as 62 thousand 958
        thousands = "sáu mươi hai nghìn chín trăm năm mươi tám"
        self.assertEqual(numbers_vi.speak_text("62.958 sao"), f"{thousands} sao")
        self.assertEqual(numbers_vi.speak_text("62,958 sao"), f"{thousands} sao")
        self.assertEqual(numbers_vi.speak_text("1,234,567"), "một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy")
        # a decimal, and a number whose first group starts with 0, are not thousands in either place
        self.assertEqual(numbers_vi.speak_text("3,5 và 0,125"), "ba phẩy năm và không phẩy một hai năm")
        self.assertEqual(numbers_vi.speak_text("0.125"), "không chấm một hai năm")
        self.assertEqual(check_facts.numbers("0,125 và 0.125"), {"0.125"})
        self.assertEqual(check_facts.numbers("62,958"), {"62958"})

    def test_a_command_is_found_as_a_whole_row_not_inside_another_one(self):
        commands = ["npm install", "npm install foo", "npm run dev"]
        digest = digest_with(lambda d: d["draft"]["try_it"].update(commands=commands))
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        # the first command's row is gone, but its text is still a substring of the second command
        status, output = run_gate(digest, doc, html.replace(">npm install<", "><"))
        self.assertEqual(status, 1)
        self.assertIn("'npm install'", output)
        # a command listed twice has to be shown twice
        twice = digest_with(lambda d: d["draft"]["try_it"].update(commands=["bun run dev", "bun run dev"]))
        plan = planlib.build_plan(twice)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(twice, doc, html)[0], 0)
        self.assertEqual(run_gate(twice, doc, html.replace(">bun run dev<", "><", 1))[0], 1)
        # commands with characters that HTML escapes are still found
        special = digest_with(lambda d: d["draft"]["try_it"].update(commands=["cd app && bun run dev > out.log", "echo '<ok>'"]))
        plan = planlib.build_plan(special)
        tl = planlib.timeline(plan, estimated_durations(plan))
        self.assertEqual(run_gate(special, make_video.voiceover_doc(plan, tl), compose.render(plan, tl))[0], 0)

    def test_html_that_is_never_closed_hides_nothing_from_the_gate(self):
        def parts(markup):
            parser = check_facts.Visible()
            parser.feed(markup)
            parser.close()
            return parser.parts
        # a data-label element left open at the end of the file is read like the rest of the page...
        self.assertEqual(parts("<div data-label>Dùng ElevenLabs"), ["Dùng ElevenLabs"])
        self.assertEqual(parts("<div data-label><b>Dùng</b> ElevenLabs"), ["Dùng ElevenLabs"])
        # ...unless it holds exactly a fixed label
        self.assertEqual(parts("<div data-label>Tự thử"), [])
        # a <head> that is never closed does not turn the rest of the page into invisible text
        self.assertEqual(parts("<html><head><meta charset=utf-8><body><p>Dùng ElevenLabs</p>"), ["Dùng ElevenLabs"])
        self.assertEqual(parts("<html><head><style>.a { color: red }</style><script>var x = 99999;</script></head><body>ok"), ["ok"])
        # and the same through the gate, on a real composition
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        self.assertEqual(run_gate(digest, doc, html + "<div data-label>ElevenLabs nhanh gấp 99999 lần")[0], 1)
        self.assertEqual(run_gate(digest, doc, html.replace("</head>", "", 1))[0], 0)
        self.assertEqual(run_gate(digest, doc, html.replace("</head>", "", 1).replace("</body>", "<p>ElevenLabs nhanh gấp 99999 lần</p></body>", 1))[0], 1)

    def test_a_name_must_be_found_as_a_whole_word_in_the_values_of_the_source(self):
        source = check_facts.blob({"field": "Cài bằng pnpm install, giấy phép AGPL-3.0, tải ở https://bun.sh/install"})
        self.assertEqual(check_facts.untraced("npm install", source, set()), ["token 'npm'"])          # npm is inside pnpm only
        self.assertEqual(check_facts.untraced("pnpm install", source, set()), [])
        self.assertEqual(check_facts.untraced("AGPL và AGPL-3.0", source, set()), [])                  # a part of a name, cut at a hyphen
        self.assertEqual(check_facts.untraced("bun.sh", source, set()), [])                            # a name inside an address
        self.assertEqual(check_facts.untraced("pn", source, set()), ["token 'pn'"])
        self.assertEqual(check_facts.untraced("installer", source, set()), ["token 'installer'"])
        # the keys of the source are its structure, not facts
        structure = check_facts.blob({"license": "MIT", "commands": ["bun run dev"], "stars": 62958})
        self.assertEqual(check_facts.untraced("license commands", structure, set()), ["token 'license'", "token 'commands'"])
        self.assertEqual(check_facts.untraced("MIT, bun run dev", structure, set()), [])
        self.assertEqual(check_facts.untraced("62.958", structure, set()), [])                         # numbers count as values
        # and through the gate: a line reworded from pnpm to npm is refused
        digest = digest_with(lambda d: d["draft"].update(hook="Cài bằng pnpm install là xong"))
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        doc["lines"][0]["text"] = doc["lines"][0]["text"].replace("pnpm", "npm")
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 1)
        self.assertIn("token 'npm'", output)

    def test_a_digest_without_its_url_is_refused_not_given_an_invented_one(self):
        def drop_url(d):
            d["facts"].pop("url")
        with self.assertRaises(ValueError) as caught:
            digest_with(drop_url)
        self.assertIn("facts.url", str(caught.exception))
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        self.assertEqual(plan["url_text"], "github.com/debpalash/VoiceStudio")                      # the address of the digest itself

    def test_a_name_with_more_after_it_is_not_the_shorter_name(self):
        source = check_facts.blob({"stack": "faster-whisper-large-v3 và Python-based, repo debpalash/VoiceStudio, chạy bun run setup:api",
                                   "license": "AGPL-3.0 hoặc Apache-2.0", "model": "gpt-4o và v2.1.3"})
        untraced = lambda text, allow=(): check_facts.untraced(text, source, set(allow))
        self.assertEqual(untraced("faster-whisper-large-v3"), [])
        self.assertEqual(untraced("faster-whisper"), ["token 'faster-whisper'"])         # another model, not the one the source names
        self.assertEqual(untraced("whisper large"), ["token 'whisper'", "token 'large'"])
        self.assertEqual(untraced("gpt"), ["token 'gpt'"])                                # gpt-4o is not gpt
        self.assertEqual(untraced("Python"), ["token 'Python'"])
        self.assertEqual(untraced("Python", allow=["python"]), [])                         # the explicit way out, per word
        # a name followed only by a version is still that name; so is each path segment of owner/repo
        self.assertEqual(untraced("AGPL và Apache, giấy phép AGPL-3.0"), [])
        self.assertEqual(untraced("VoiceStudio, debpalash/VoiceStudio, github.com/debpalash/VoiceStudio"), ["token 'github.com/debpalash/VoiceStudio'"])
        self.assertEqual(untraced("bun run setup:api, setup, api"), [])
        self.assertEqual(untraced("v2.1.3"), [])
        self.assertEqual(untraced("v2.1"), ["number 2.1", "token 'v2.1'"])

    def test_a_digest_whose_url_carries_credentials_is_refused_before_anything_is_written(self):
        for url in ("https://user:ghp_SECRET@example.com/o/r", "https://ghp_SECRET@github.com/o/r", "http://u:p@example.com/o/r"):
            with self.assertRaises(ValueError) as caught:
                digest_with(lambda d: d["facts"].update(url=url))
            self.assertIn("facts.url", str(caught.exception))
            self.assertNotIn("SECRET", str(caught.exception))                       # the message does not repeat the secret
        planlib.load_digest(FIXTURES / "voicestudio.json")                           # an ordinary address is fine
        digest = fixture("voicestudio")
        digest["facts"]["url"] = "https://user:ghp_SECRET@example.com/o/r"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "draft-vi.json"
            source.write_text(json.dumps(digest), encoding="utf-8")
            result = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "radar" / "make_video.py"), "scaffold", str(source),
                                     "--name", "leak", "--videos-dir", str(Path(tmp) / "videos")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SECRET", result.stdout + result.stderr)
            self.assertFalse((Path(tmp) / "videos").exists(), "no project, and no copy of the digest, is created")

    def test_code_in_the_page_cannot_put_words_on_the_screen_unseen(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)            # its own style (content: "") and script (GSAP calls) are fine
        sneaky = {
            "css text": html.replace("</style>", '#root::after { content: "99999 lần" }</style>', 1),
            "css attr": html.replace("</style>", '#root::after { content: attr(data-start) }</style>', 1),
            "css import": html.replace("<style>", '<style>@import url("https://example.com/x.css");', 1),
            "script text": html.replace("</body>", '<script>document.body.appendChild(Object.assign(document.createElement("p"), '
                                        '{ textContent: "ElevenLabs nhanh gấp 99999 lần" }))</script></body>', 1),
            "script html": html.replace("</body>", '<script>document.getElementById("root").innerHTML = "x"</script></body>', 1),
            "script load": html.replace("</body>", '<script>fetch("https://example.com/x").then(r => r.text())</script></body>', 1),
            "script src": html.replace("</head>", '<script src="https://example.com/x.js"></script></head>', 1),
            "script src (protocol-relative)": html.replace("</head>", '<script src="//example.com/x.js"></script></head>', 1),
            "event handler": html.replace("</body>", '<img src="x.png" onerror="document.title=1"></body>', 1),
            "frame": html.replace("</body>", '<iframe src="https://example.com"></iframe></body>', 1),
            "stylesheet": html.replace("</head>", '<link rel="stylesheet" href="https://example.com/x.css"></head>', 1),
            "base": html.replace("<head>", '<head><base href="https://attacker.example/assets/">', 1),
            "canvas": html.replace("</body>", '<canvas id="c"></canvas><script>document.getElementById("c").getContext("2d").fillText("99999 lần", 10, 10)</script></body>', 1),
            "canvas text": html.replace("</body>", '<script>ctx.strokeText("99999", 0, 0)</script></body>', 1),
        }
        for name, changed in sneaky.items():
            status, output = run_gate(digest, doc, changed)
            self.assertEqual(status, 1, name)
            self.assertIn("put words on the screen or load code", output, name)
        # a file next to the page is not trusted for being local: only the template's own gsap.min.js, byte for byte
        for name, changed, files in (
                ("other script", html.replace("</head>", '<script src="evil.js"></script></head>', 1), {"evil.js": "document.title = 1"}),
                ("other stylesheet", html.replace("</head>", '<link rel="stylesheet" href="evil.css"></head>', 1), {"evil.css": "a{}"}),
                ("edited gsap", html, {"gsap.min.js": "/* the template's gsap, with something added */"}),
                ("path to gsap", html.replace('src="gsap.min.js"', 'src="./gsap.min.js"', 1), {})):
            status, output = run_gate(digest, doc, changed, files)
            self.assertEqual(status, 1, name)
            self.assertIn("put words on the screen or load code", output, name)
        same_file = html.replace('src="gsap.min.js"', 'src="gsap.min.js" data-start="0"', 1)                       # an attribute is not a file
        self.assertEqual(run_gate(digest, doc, same_file)[0], 0)

    def test_elements_and_attributes_the_template_never_uses_are_refused(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        for name, changed in (
                ("input value", html.replace("</body>", '<input value="ElevenLabs nhanh gấp 99999 lần"></body>', 1)),
                ("input placeholder", html.replace("</body>", '<input placeholder="Dùng ElevenLabs"></body>', 1)),
                ("image alt", html.replace("</body>", '<img src="missing.png" alt="ElevenLabs 99999"></body>', 1)),
                ("option label", html.replace("</body>", '<option label="Dùng ElevenLabs"></option></body>', 1)),
                ("value on a div", html.replace("<body>", '<body><div value="Dùng ElevenLabs"></div>', 1)),
                ("meta refresh", html.replace("<head>", '<head><meta http-equiv="refresh" content="0;url=evil.html">', 1)),
                ("object", html.replace("</body>", '<object data="evil.html"></object></body>', 1)),
                ("svg", html.replace("</body>", '<svg><text>ElevenLabs 99999</text></svg></body>', 1)),
                ("title", html.replace("<head>", '<head><title>ElevenLabs</title>', 1)),
                ("event handler", html.replace("<body>", '<body onload="x()">', 1)),
                ("sub-composition", html.replace("<body>", '<body><div data-composition-src="evil.html"></div>', 1)),
                ("another data attribute", html.replace("<body>", '<body><div data-anything="x"></div>', 1)),
                ("script src twice", html.replace('<script src="gsap.min.js">', '<script src="evil.js" src="gsap.min.js">', 1)),
                ("script src twice, reversed", html.replace('<script src="gsap.min.js">', '<script src="gsap.min.js" src="evil.js">', 1)),
                ("id twice", html.replace("<body>", '<body><div id="a" id="b"></div>', 1))):
            status, output = run_gate(digest, doc, changed)
            self.assertEqual(status, 1, name)
            self.assertIn("put words on the screen or load code", output, name)

    def test_the_script_and_style_of_the_page_are_held_to_the_template(self):
        template_script = re.search(r"<script>(.*?)</script>", compose.render(*self.rendered_plan()), re.S).group(1)
        self.assertEqual(check_facts.js_problems(template_script), [])
        pilot = (REPO / "videos" / "voicestudio" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(check_facts.js_problems(re.findall(r"<script>(.*?)</script>", pilot, re.S)[0]), [])
        for what, js in (("DOM text", 'el.firstChild.data = "ElevenLabs 99999"'), ("replaceData", 'el.firstChild.replaceData(0, 1, "x")'),
                         ("innerHTML", 'tl.set("#a", { innerHTML: "x" })'), ("quoted key", 'tl.set("#a", { "innerHTML": "x" })'),
                         ("obfuscated", 'window["inner" + "HTML"] = "x"'), ("computed", 'window["document"]'),
                         ("template literal", "tl.set(`#a`, { opacity: 0 })"), ("eval", 'eval("x")'), ("fetch", 'fetch("https://example.com")'),
                         ("canvas", 'c.getContext("2d").fillText("x", 0, 0)'), ("ternary", "x ? y : z"), ("regex", "/a/.test(b)"),
                         ("comment hides nothing", '// harmless\ndocument.title = 1')):
            self.assertTrue(check_facts.js_problems(js), what)
        # comments and strings that merely contain words are fine
        self.assertEqual(check_facts.js_problems('// scene starts, equal to the data-start\ntl.set("#a", { opacity: 0 }, S1 + 2.5);'), [])
        template_style = re.search(r"<style>(.*?)</style>", compose.render(*self.rendered_plan()), re.S).group(1)
        self.assertEqual(check_facts.css_problems(template_style), [])
        self.assertEqual(check_facts.css_problems("font-size: 38px", inline=True), [])
        for what, css in (("list marker", ".a { list-style-type: '99999' }"), ("quotes", ".a { quotes: '99999' '' }"),
                          ("content", ".a::after { content: '99999' }"), ("counter", ".a::after { counter-increment: x }"),
                          ("attr", ".a::after { content: attr(data-x) }"), ("import", "@import 'x.css';"), ("url", ".a { background: url(x.png) }"),
                          ("escape", ".a { c\\6f ntent: 'x' }"), ("animation", ".a { animation: x 1s }")):
            self.assertTrue(check_facts.css_problems(css), what)
        self.assertTrue(check_facts.css_problems("list-style-type: '9'", inline=True))

    def test_a_style_may_not_load_an_image_or_hide_what_the_gate_counts(self):
        for what, css in (("image-set", ".a { background: image-set('evil.svg' 1x) }"), ("prefixed", ".a { background: -webkit-image-set('e.svg' 1x) }"),
                          ("cross-fade", ".a { background: cross-fade(a, b, 50%) }"), ("element", ".a { background: element(#x) }"),
                          ("custom property", ":root { --x: image-set('evil.svg' 1x) } .a { background: var(--x) }")):
            self.assertTrue(check_facts.css_problems(css), what)
        self.assertEqual(check_facts.css_problems(".a { background: radial-gradient(ellipse at 50% 38%, rgba(255, 157, 46, 0.16), transparent 70%), "
                                                  "linear-gradient(var(--line) 1px, transparent 1px); color: var(--ink) }"), [])
        # an inline style may only set the font size: display:none, opacity, offsets are how a required row could be hidden
        self.assertEqual(check_facts.css_problems("font-size: 38px", inline=True), [])
        for hide in ("display:none", "opacity:0", "position:absolute;left:-9999px", "font-size:38px;visibility:hidden", "color:transparent"):
            self.assertTrue(check_facts.css_problems(hide, inline=True), hide)
        digest = digest_with(lambda d: d["draft"]["try_it"].update(commands=["bun run dev", "bun run build"]))
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        hidden = html.replace(">bun run dev<", "><", 1).replace("</body>", '<div style="display:none">bun run dev</div></body>', 1)
        status, output = run_gate(digest, doc, hidden)
        self.assertEqual(status, 1)
        self.assertIn("an inline style that sets the property `display`", output)

    def test_a_name_glued_to_a_vietnamese_letter_is_still_checked(self):
        source = check_facts.blob({"x": "VoiceStudio, tiếng Việt, ông Nguyễn Văn An ở Hà Nội"})
        untraced = lambda text: check_facts.untraced(text, source, set())
        self.assertEqual(untraced("ElevenLabsé"), ["token 'ElevenLabs'"])
        self.assertEqual(untraced("ElevenLabsế và VoiceStudioé"), ["token 'ElevenLabs'"])      # a name the source has, with a letter glued on, is that name
        # Vietnamese words are not names: no syllable has five ASCII letters in a row
        self.assertEqual(untraced("tiếng Việt thương nghiêng khuyến chuyển nghĩa quyền thuyết Nguyễn trường Hồ-Chí-Minh"), [])
        self.assertTrue(all(len(run) <= 4 for word in "nghiêng khuyến chuyển nghĩa quyền thuyết Nguyễn trường thương khuỷu".split()
                            for run in re.findall(r"[A-Za-z]+", word)))

    def test_a_render_without_audible_sound_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            def make(name, audio):
                path = Path(tmp) / name
                cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1"] + audio + ["-t", "1", str(path)]
                subprocess.run(cmd, check=True)
                return path
            tone = make("tone.mp4", ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac"])
            silent = make("silent.mp4", ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-c:a", "aac"])
            video_only = make("video-only.mp4", [])
            levels = {name: make_video.whole_file_levels(path) for name, path in (("tone", tone), ("silent", silent), ("none", video_only))}
        self.assertIsNone(levels["none"][0])
        make_video.require_audible(*levels["tone"])                                  # a voice-level sound is accepted
        for name in ("silent", "none"):
            with self.assertRaises(SystemExit, msg=name):
                make_video.require_audible(*levels[name])
        with self.assertRaises(SystemExit):
            make_video.require_audible(float("-inf"), float("-inf"))

    def test_a_compound_name_must_be_written_as_one_in_the_source(self):
        source = check_facts.blob({"url": "https://github.com/debpalash/VoiceStudio", "note": "OmniVoice là một mô hình", "cmd": "bun run setup:api"})
        untraced = lambda text: check_facts.untraced(text, source, set())
        self.assertEqual(untraced("https://github.com/debpalash/VoiceStudio, github.com/debpalash/VoiceStudio, debpalash/VoiceStudio"), [])
        self.assertEqual(untraced("setup:api và bun run setup:api"), [])
        # every part is in the source, but not written together: a made-up address
        self.assertEqual(untraced("https://github.com/debpalash/omnivoice"), ["token 'https://github.com/debpalash/omnivoice'"])
        self.assertEqual(untraced("github.com/OmniVoice/VoiceStudio"), ["token 'github.com/OmniVoice/VoiceStudio'"])
        self.assertEqual(untraced("api:setup"), ["token 'api:setup'"])
        self.assertEqual(untraced("debpalash/OmniVoice"), ["token 'debpalash/OmniVoice'"])
        self.assertEqual(untraced("VoiceStudio và OmniVoice"), [])                 # separate names are still fine

    def test_a_compound_name_is_not_found_inside_a_longer_one(self):
        parts = {"a": "repo", "b": "example", "c": "x", "d": "foo.com", "e": "https", "f": "c"}
        longer = check_facts.blob({**parts, "url": "https://foo.com/example/repo-extra", "other": "my-foo.com/x", "lang": "github.com/o/c++"})
        untraced = lambda text, source=longer: check_facts.untraced(text, source, set())
        # every part is a name of the source, but the address is only there with something after (or before) it
        self.assertEqual(untraced("https://foo.com/example/repo"), ["token 'https://foo.com/example/repo'"])
        self.assertEqual(untraced("foo.com/x"), ["token 'foo.com/x'"])
        self.assertEqual(untraced("github.com/o/c"), ["token 'github.com/o/c'"])
        self.assertEqual(untraced("https://foo.com/example/repo-extra"), [])
        whole = check_facts.blob({**parts, "url": "https://foo.com/example/repo", "other": "see foo.com/x."})
        self.assertEqual(untraced("https://foo.com/example/repo, foo.com/x.", whole), [])      # a full stop or a comma after it ends it
        self.assertEqual(untraced("https://foo.com/example/repo.git", whole), ["token 'https://foo.com/example/repo.git'"])

    def test_a_short_name_glued_to_a_letter_is_still_checked(self):
        source = check_facts.blob({"field": "VoiceStudio chạy cục bộ"})
        untraced = lambda text, source=source: check_facts.untraced(text, source, set())
        for glued, name in (("GPTé", "GPT"), ("npmé", "npm"), ("C++é", "C++"), ("Việt-GPTé", "GPT"), ("éGPT", "GPT"), ("Tōkyō", "ky")):
            self.assertEqual(untraced(glued), [f"token '{name}'"], glued)
        self.assertEqual(untraced("GPTé", check_facts.blob({"field": "dùng GPT"})), [])            # the name the source has, with a letter glued on
        self.assertEqual(untraced("GPTé", check_facts.blob({"field": "dùng GPTé"})), [])
        # a syllable of Vietnamese is a word, not a name, whatever it is made of
        self.assertEqual(untraced("Việt, Hà Nội, Hồ-Chí-Minh, nghiêng, khuỷu, Nguyễn, quyển, thuyền, uống, ngoằn, Đức, ừm, ý, giường, gì, loắt, hoặc"), [])
        self.assertTrue(all(check_facts.vietnamese_syllable(word) for word in ("Việt", "Đà", "nghiêng", "ừ", "ơ", "Huế", "yêu", "khuỷu")))
        self.assertFalse(any(check_facts.vietnamese_syllable(word) for word in ("GPTé", "npmé", "C++é", "Müller", "café")))

    def test_text_that_touches_in_the_markup_is_read_as_the_browser_shows_it(self):
        def read(markup):
            parser = check_facts.Visible()
            parser.feed(f"<body>{markup}</body>")
            parser.close()
            return parser.glued
        self.assertEqual(read("<div><span>Open</span><span>AI</span></div>"), ["OpenAI"])
        self.assertEqual(read("<b>G</b><i>P</i><span>T</span>"), ["GPT"])                      # a run of any length
        self.assertEqual(read("<span>Open </span><span>AI</span>"), [])                       # a space on either side is a gap
        self.assertEqual(read("<span>Open</span> <span>AI</span>"), [])
        self.assertEqual(read("<span>Open</span>\n<span>AI</span>"), [])
        self.assertEqual(read("<div>Open</div><div>AI</div>"), [])                            # blocks and line breaks separate
        self.assertEqual(read("<p>Open</p><p>AI</p>"), [])
        self.assertEqual(read("<span>Open</span><br><span>AI</span>"), [])
        self.assertEqual(read("<b>62.958</b><span data-label>sao</span>"), ["62.958sao"])       # a template label touches too
        # end to end: both words are in the digest, the name made of them is not
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        digest["facts"]["first"], digest["facts"]["second"] = "Open", "AI"
        status, _ = run_gate(digest, doc, html)
        self.assertEqual(status, 0)
        status, output = run_gate(digest, doc, html.replace("</body>", "<div><span>Open</span><span>AI</span></div></body>", 1))
        self.assertEqual(status, 1)
        self.assertIn("OpenAI", output)
        status, _ = run_gate(digest, doc, html.replace("</body>", "<div><span>Open</span> <span>AI</span></div></body>", 1))
        self.assertEqual(status, 0)

    def test_a_character_that_draws_nothing_does_not_split_a_name_or_a_number(self):
        source = check_facts.blob({"field": "VoiceStudio chạy cục bộ", "n": "1 người, 9%"})
        untraced = lambda text, source=source: check_facts.untraced(text, source, set())
        for glued in ("G​P​T", "G‍P‌T", "G­PT", "G⁠P⁠T", "G﻿PT", "G‎PT", "G\x00PT", "G\U000e0041PT"):
            self.assertEqual(untraced(glued), ["token 'GPT'"], repr(glued))
        self.assertEqual(untraced("G​P​T", check_facts.blob({"field": "dùng GPT"})), [])        # the name the source has
        self.assertEqual(check_facts.numbers("tăng 1​9%"), {"19%"})                                   # nor a number
        self.assertEqual(untraced("1​9%"), ["number 19%"])                                           # 1 and 9% are in the source, 19% is not
        # a symbol or a space is drawn or is a gap, so it still separates the letters (letters apart like that spell the name, see below)
        self.assertEqual(untraced("G™P™T"), ["token 'GPT'"])
        self.assertEqual(untraced("G P　T"), ["token 'GPT'"])

    def test_a_percentage_is_read_whatever_the_case_of_its_words(self):
        for text in ("19 phần trăm", "19 PHẦN TRĂM", "19 Phần Trăm", "19 phần  trăm", "19 phần trăm", "19%", "19 %", "19％", "19﹪", "19٪"):
            self.assertEqual(check_facts.numbers(text), {"19%"}, text)
        plain = check_facts.blob({"fact": "19 người"})
        for text in ("19 PHẦN TRĂM", "19％", "19 Phần Trăm"):
            self.assertEqual(check_facts.untraced(text, plain, set()), ["number 19%"], text)             # the source states no percentage
        self.assertEqual(check_facts.untraced("19 PHẦN TRĂM", check_facts.blob({"fact": "19 phần trăm"}), set()), [])
        self.assertEqual(check_facts.numbers("19 PHẦN TRĂM".replace("Ầ", "Ầ")), {"19%"})        # decomposed, as pasted text can be
        self.assertEqual(numbers_vi.speak_text("tăng 19％ và 5﹪"), "tăng mười chín phần trăm và năm phần trăm")

    def test_a_look_alike_of_a_sign_is_the_sign(self):
        for text, value in (("＋19%", "+19%"), ("﹢19%", "+19%"), ("➕19", "+19"), ("⁺3,5", "+3.5"),
                            ("－19%", "-19%"), ("﹣19%", "-19%"), ("➖3", "-3"), ("⁻3", "-3"), ("‐3", "-3"), ("−3", "-3")):
            self.assertEqual(check_facts.numbers(text), {value}, text)
        plain = check_facts.blob({"fact": "tăng 19%"})
        for text in ("＋19%", "﹢19%", "－19%", "➖19%"):
            self.assertEqual(check_facts.untraced(text, plain, set()), [f"number {'+' if text[0] in '＋﹢' else '-'}19%"], text)   # the sign is the part that is not in the source
        self.assertEqual(check_facts.untraced("＋19%", check_facts.blob({"fact": "+19%"}), set()), [])
        # the voice says what the gate traced
        self.assertEqual(numbers_vi.speak_text("tăng ＋19% và ﹢5"), "tăng cộng mười chín phần trăm và cộng năm")
        self.assertEqual(numbers_vi.speak_text("giảm －19%, ➖3,5 và ⁻2"), "giảm âm mười chín phần trăm, âm ba phẩy năm và âm hai")
        self.assertEqual(numbers_vi.speak_text("AGPL－3.0"), numbers_vi.speak_text("AGPL-3.0"))        # a version, not a negative number
        # after a letter or a digit it is not a sign, as for the ASCII ones
        self.assertEqual(check_facts.numbers("1＋1 và x＋5 và 10‐20 và AGPL－3.0"), {"1", "5", "10", "20", "3.0"})

    def test_single_letters_apart_by_spaces_are_read_as_the_name_they_spell(self):
        source = check_facts.blob({"fact": "VoiceStudio chạy cục bộ"})
        untraced = lambda text, source=source: check_facts.untraced(text, source, set())
        self.assertEqual(untraced("G P T"), ["token 'GPT'"])
        self.assertEqual(untraced("G  P T"), ["token 'GPT'"])                           # any spaces within the line
        self.assertEqual(untraced("G P T", check_facts.blob({"fact": "dùng GPT"})), [])        # the name the source has
        self.assertEqual(untraced("G P T", check_facts.blob({"fact": "dùng G P T"})), [])      # or spelled the same way
        # not a row: a comma, a line break or a longer word between them
        self.assertEqual(untraced("A và B, C"), [])
        self.assertEqual(untraced("G, P, T"), [])
        self.assertEqual(untraced("G\nP\nT"), [])
        self.assertEqual(untraced("G (P) T"), [])

    def test_the_narration_has_to_be_in_the_render_not_just_the_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "assets").mkdir()
            def ffmpeg(*args):
                subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)
            ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=6,volume=-8.7dB", str(project / "assets" / "pad.wav"))        # about -30 dB, like the real bed
            ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2,volume=1dB", str(project / "assets" / "vo-1.wav"))             # about -20 dB, like the voice
            (project / "index.html").write_text('<audio id="music-bed" src="assets/pad.wav" data-start="0" data-duration="6" data-volume="0.6"></audio>',
                                                encoding="utf-8")
            doc = {"lines": [{"id": "vo-1", "start": 2.0}]}
            (project / "voiceover.json").write_text(json.dumps(doc), encoding="utf-8")
            music_only = project / "music-only.mp4"
            with_voice = project / "with-voice.mp4"
            ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:d=6", "-i", str(project / "assets" / "pad.wav"),
                   "-filter_complex", "[1:a]volume=0.6[a]", "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-t", "6", str(music_only))
            ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:d=6", "-i", str(project / "assets" / "pad.wav"), "-i", str(project / "assets" / "vo-1.wav"),
                   "-filter_complex", "[1:a]volume=0.6[m];[2:a]adelay=2000|2000[v];[m][v]amix=inputs=2:duration=first:normalize=0[a]",
                   "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-t", "6", str(with_voice))
            pad_alone = make_video.whole_file_levels(project / "assets" / "pad.wav")[0]
            self.assertAlmostEqual(make_video.music_bed_db(project), pad_alone + 20 * math.log10(0.6), delta=0.5)   # its own level, times 0.6
            self.assertEqual(make_video.silent_narration(project, doc, music_only), ["vo-1"])           # the music alone clears -45 dB, and is not a voice
            self.assertEqual(make_video.silent_narration(project, doc, with_voice), [])
            self.assertTrue(make_video.whole_file_levels(music_only)[0] > make_video.AUDIBLE_DB)

    def test_the_style_block_is_the_templates_so_it_cannot_hide_a_row(self):
        digest = digest_with(lambda d: d["draft"]["try_it"].update(commands=["bun run dev", "bun run build"]))
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        for what, changed in (("hide commands", html.replace("</style>", ".term .cmd { display: none }</style>", 1)),
                              ("transparent", html.replace("</style>", ".term .cmd { color: transparent }</style>", 1)),
                              ("off screen", html.replace("</style>", ".term .cmd { position: absolute; left: -9999px }</style>", 1)),
                              ("any other change", html.replace("overflow: hidden", "overflow: visible", 1)),
                              ("a second block", html.replace("</head>", "<style>.a { color: red }</style></head>", 1)),
                              ("no block", re.sub(r"<style>.*?</style>", "", html, flags=re.S))):
            self.assertNotEqual(changed, html, what)
            status, output = run_gate(digest, doc, changed)
            if what == "no block":
                self.assertEqual(status, 0, what)       # no style at all hides nothing, and is not a way to put words on the screen
                continue
            self.assertEqual(status, 1, what)
            self.assertIn("a style that is not the template's", output, what)
        # compose.py's style and the hand-made pilot's are the two the check knows; changing either one has to be a decision
        norm = lambda css: check_facts.style_fingerprint(css)
        self.assertIn(norm(re.search(r"<style>(.*?)</style>", html, re.S).group(1)), check_facts.TRUSTED_STYLES)
        pilot = (REPO / "videos" / "voicestudio" / "index.html").read_text(encoding="utf-8")
        self.assertIn(norm(re.search(r"<style>(.*?)</style>", pilot, re.S).group(1)), check_facts.TRUSTED_STYLES)
        auto = (REPO / "videos" / "voicestudio-auto" / "index.html").read_text(encoding="utf-8")
        self.assertIn(norm(re.search(r"<style>(.*?)</style>", auto, re.S).group(1)), check_facts.TRUSTED_STYLES)
        # whitespace in the block does not matter
        reflowed = re.sub(r"<style>(.*?)</style>", lambda m: "<style>" + re.sub(r"\s+", "\n  ", m.group(1)) + "</style>", html, flags=re.S)
        self.assertEqual(run_gate(digest, doc, reflowed)[0], 0)

    def test_each_voice_line_plays_its_own_clip(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        ids = [line["id"] for line in doc["lines"]]
        self.assertGreaterEqual(len(ids), 3)
        for what, changed in (
                ("every line plays the first clip", re.sub(r'(id="vo-(?!1")\d+" src=")assets/vo-\d+\.wav', r"\1assets/vo-1.wav", html)),
                ("one clip is another's", html.replace('src="assets/vo-2.wav"', 'src="assets/vo-1.wav"', 1)),
                ("a clip from elsewhere", html.replace('src="assets/vo-2.wav"', 'src="assets/../vo-2.wav"', 1)),
                ("a line without its clip", re.sub(r'<audio id="vo-3"[^>]*></audio>', "", html)),
                ("an audio element nobody asked for", html.replace("</body>", '<audio id="extra" src="assets/vo-1.wav" data-start="0" data-duration="1"></audio></body>', 1)),
                ("the music bed is a voice clip", html.replace('src="assets/pad.wav"', 'src="assets/vo-1.wav"', 1))):
            self.assertNotEqual(changed, html, what)
            status, output = run_gate(digest, doc, changed)
            self.assertEqual(status, 1, what)
            self.assertIn("audio", output, what)

    def test_the_solution_sentence_is_the_one_that_names_the_tool_not_one_that_contains_its_name(self):
        sentences = ["Nhiều nhóm gặp khó khăn.", "Họ lưu dữ liệu trong MongoDB và tự viết mã lặp lại.", "Go giúp xây dựng dịch vụ nhanh gọn.", "Kết thúc."]
        self.assertEqual(planlib.solution_index(sentences, "Go"), 2)              # MongoDB contains "go", but it is not Go
        self.assertEqual(planlib.solution_index(sentences, "go"), 2)
        self.assertEqual(planlib.solution_index(["a", "Bạn dùng go-task để chạy.", "Go chạy nhanh."], "Go"), 2)    # go-task is another name
        self.assertEqual(planlib.solution_index(["a", "VoiceStudio's chạy cục bộ.", "b"], "VoiceStudio"), 1)      # a possessive is still the name
        self.assertEqual(planlib.solution_index(["a", "(VoiceStudio) chạy cục bộ.", "b"], "voicestudio"), 1)
        self.assertEqual(planlib.solution_index(["a", "Không có tên.", "Cũng không."], "Go"), 2)                  # none names it: the last one
        # a + or # after a name belongs to it, as the facts gate reads names: C is not C++ or C#
        self.assertEqual(planlib.solution_index(["a", "C++ nhanh hơn nhiều.", "C là ngôn ngữ cũ."], "C"), 2)
        self.assertEqual(planlib.solution_index(["a", "Viết bằng C#.", "C đơn giản."], "C"), 2)
        self.assertEqual(planlib.solution_index(["a", "C++ nhanh.", "Cũng vậy."], "C++"), 1)                      # the name with its signs is found
        self.assertEqual(planlib.solution_index(["a", "C, C++ và Go.", "Kết thúc."], "C"), 1)                      # a comma after it ends it

    def test_the_page_of_a_generated_project_is_what_compose_writes(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "source").mkdir()
            (project / "assets").mkdir()
            (project / "source" / "draft-vi.json").write_text(json.dumps(fixture("voicestudio")), encoding="utf-8")
            shutil.copyfile(REPO / "scripts" / "radar" / "assets" / "gsap.min.js", project / "gsap.min.js")
            durations = {}
            for unit in plan["units"]:
                durations[unit["id"]] = unit["est"]
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(unit["est"]),
                                str(project / "assets" / f"{unit['id']}.wav")], check=True)
            tl = planlib.timeline(plan, {uid: make_video.clip_seconds(project / "assets" / f"{uid}.wav") for uid in durations})
            make_video.write_composition(project, plan, tl)
            make_video.make_pad(project / "assets" / "pad.wav", tl["duration"])
            page = project / "index.html"
            original = page.read_text(encoding="utf-8")
            make_video.require_generated_page(project)                                  # what voice wrote is what compose writes
            # revoice.py sets the level of each voice clip, nothing else
            page.write_text(re.sub(r'(<audio id="vo-1"[^>]*?) data-volume="[^"]*"', r'\1 data-volume="1.37"', original), encoding="utf-8")
            make_video.require_generated_page(project)
            tampered = {
                "gsap hides the commands": original.replace("window.__timelines[", 'tl.set(".term .cmd", { opacity: 0 }, 0);\n      window.__timelines[', 1),
                "a statement of the template's own kind on a command": original.replace("window.__timelines[", 'fadeOut("#s5-cmd0", 1);\n      window.__timelines[', 1),
                "the music bed is turned up": original.replace('id="music-bed" src="assets/pad.wav" data-start="0"', 'id="music-bed" src="assets/pad.wav" data-start="5"', 1),
                "a timing moved": re.sub(r'(<section id="s2" class="clip" data-start=")[\d.]+', r"\g<1>1", original, count=1),
                "a word of the page changed": original.replace(">Python<", ">Python hơn<", 1),
                "a comment": original.replace("</body>", "<!-- note --></body>", 1),
            }
            for what, changed in tampered.items():
                self.assertNotEqual(changed, original, what)
                page.write_text(changed, encoding="utf-8")
                with self.assertRaises(SystemExit, msg=what):
                    make_video.require_generated_page(project)
            # rebuild writes the page again from the digest and the clips, with no model and no network
            args = type("Args", (), {"project": str(project), "videos_dir": tmp})()
            make_video.cmd_rebuild(args, project)
            make_video.require_generated_page(project)
            self.assertEqual(page.read_text(encoding="utf-8"), original)
            page.write_text(re.sub(r'(<audio id="vo-1"[^>]*?) data-volume="[^"]*"', r'\1 data-volume="1.37"', original), encoding="utf-8")
            make_video.cmd_rebuild(args, project)                                       # the level that revoice.py set is kept
            self.assertIn('id="vo-1" src="assets/vo-1.wav"', page.read_text(encoding="utf-8"))
            self.assertRegex(page.read_text(encoding="utf-8"), r'<audio id="vo-1"[^>]*data-volume="1.37"')
            make_video.require_generated_page(project)
            # a clip that is missing is named, not a traceback
            (project / "assets" / "vo-2.wav").unlink()
            with self.assertRaises(SystemExit):
                make_video.require_generated_page(project)

    def rendered_plan(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        return plan, planlib.timeline(plan, estimated_durations(plan))

    def test_allow_may_list_only_vietnamese_words_not_names(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        invented = html.replace(">Python<", ">Python và ElevenLabs<", 1)
        self.assertEqual(run_gate(digest, doc, invented)[0], 1)                       # the name is not in the digest
        doc["allow"] = ["ElevenLabs"]                                                  # the document cannot vouch for itself
        status, output = run_gate(digest, doc, invented)
        self.assertEqual(status, 1)
        self.assertIn("`allow` lists elevenlabs", output)
        doc["allow"] = ["khi", "giao", "cho", "ba", "sao"]                              # Vietnamese words without diacritics are fine
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        self.assertTrue({"khi", "giao", "cho", "ba", "sao"} <= check_facts.VIETNAMESE_WORDS)
        for tool in ("npm", "git", "bun", "pip", "go", "node", "vue", "sql", "ssh"):
            self.assertNotIn(tool, check_facts.VIETNAMESE_WORDS)

    def test_a_command_is_shown_exactly_as_the_digest_gives_it(self):
        commands = ["export V=`git describe`", 'echo "a  b"', "bun run dev"]
        digest = digest_with(lambda d: d["draft"]["try_it"].update(commands=commands))
        plan = planlib.build_plan(digest)
        self.assertEqual(plan["try"]["commands"], commands)                       # no backtick dropped, no space collapsed
        tl = planlib.timeline(plan, estimated_durations(plan))
        html, doc = compose.render(plan, tl), make_video.voiceover_doc(plan, tl)
        self.assertIn("export V=`git describe`", html)
        self.assertIn("white-space: pre-wrap", html)                               # so that the two spaces are seen as well
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        for what, changed in (("backticks", html.replace("export V=`git describe`", "export V=git describe")),
                              ("spaces", html.replace("echo &quot;a  b&quot;", "echo &quot;a b&quot;"))):
            self.assertNotEqual(changed, html, what)                               # the page really was changed
            status, output = run_gate(digest, doc, changed)
            self.assertEqual(status, 1, what)
            self.assertIn("not shown exactly", output, what)
        self.assertEqual(planlib.build_plan(digest_with(lambda d: d["draft"]["try_it"].update(commands=["  bun run dev \n"])))["try"]["commands"], ["bun run dev"])

    def test_names_are_not_cut_from_vietnamese_words_and_keep_their_plus_and_hash(self):
        vietnamese = check_facts.blob({"field": "công cụ chuyển giọng nói, đường dẫn và tiếng Việt"})
        untraced = lambda text, source=vietnamese: check_facts.untraced(text, source, set())
        self.assertEqual(untraced("C++"), ["token 'C++'"])            # c is a piece of công, not a name
        self.assertEqual(untraced("C#"), ["token 'C#'"])
        self.assertEqual(untraced("ng"), ["token 'ng'"])
        self.assertEqual(untraced("Viet"), ["token 'Viet'"])
        languages = check_facts.blob({"field": "Viết bằng C++ và C#, có cả F# và Python-based"})
        self.assertEqual(untraced("C++, C# và F#", languages), [])
        self.assertEqual(untraced("C#", check_facts.blob({"field": "Viết bằng C++"})), ["token 'C#'"])    # C# is not C++
        self.assertEqual(untraced("C++/CLI", languages), ["token 'C++/CLI'"])
        self.assertEqual(untraced("C++.", languages), [])           # a full stop after it ends the sentence, not the name

    def test_a_name_stuck_to_a_symbol_is_still_checked(self):
        source = check_facts.blob({"field": "Dùng npm để cài; mô hình faster-whisper-large-v3, tiếng Việt"})
        untraced = lambda text: check_facts.untraced(text, source, set())
        for glued in ("ElevenLabs™", "OpenAI🚀", "ElevenLabs\u200b", "Eleven\u200bLabs", "npm\u0301 và ElevenLabs®", "ElevenLabs\ufe0f"):
            self.assertTrue(any("Eleven" in problem or "OpenAI" in problem for problem in untraced(glued)), glued)
        self.assertEqual(untraced("npm™ và npm®, npm🚀"), [])                      # a symbol does not hide the name, nor invent one
        self.assertEqual(untraced("tiếng Việt, faster-whisper-large-v3™"), [])    # Vietnamese words are still not compared

    def test_a_plus_sign_is_part_of_the_value(self):
        self.assertEqual(check_facts.numbers("tăng +19% và 19%, giảm -19%"), {"+19%", "19%", "-19%"})
        self.assertEqual(check_facts.numbers("Python 3.10+ và C++ và 1+1 và x+5 và a +5"), {"3.10", "1", "5", "+5"})
        source = check_facts.blob({"field": "tăng +19% trong tuần"})
        self.assertEqual(check_facts.untraced("tăng +19%", source, set()), [])
        self.assertEqual(check_facts.untraced("tăng 19%", source, set()), ["number 19%"])           # the sign cannot be dropped
        self.assertEqual(check_facts.untraced("tăng +19%", check_facts.blob({"field": "tăng 19%"}), set()), ["number +19%"])   # nor added
        self.assertEqual(numbers_vi.speak_text("tăng +19% và +3,5"), "tăng cộng mười chín phần trăm và cộng ba phẩy năm")
        self.assertEqual(numbers_vi.speak_text("Python 3.10+ và C++ và 1+1"), "Python ba chấm một không+ và C++ và một+một")
        self.assertEqual(numbers_vi.speak_text("+19 %"), numbers_vi.speak_text("+19%"))

    def test_a_clip_made_for_older_words_is_not_rendered_with_the_new_ones(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        doc = make_video.voiceover_doc(plan, tl)
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            assets.mkdir()
            for line in doc["lines"]:
                (assets / f"{line['id']}.wav").write_bytes(f"clip of {line['id']}".encode())
            self.assertEqual(make_video.stale_voices(doc, assets), [line["id"] for line in doc["lines"]])       # nothing was voiced yet
            for line in doc["lines"]:
                line["voiced"] = make_video.voiced_fingerprint(line["text"])
                line["clip"] = make_video.clip_fingerprint(assets / f"{line['id']}.wav")
            self.assertEqual(make_video.stale_voices(doc, assets), [])
            # the file is rewritten when the project is (voice does it): the record of what was voiced stays with each line
            again = make_video.voiceover_doc(plan, tl, doc)
            self.assertEqual([(l["voiced"], l["clip"]) for l in again["lines"]], [(l["voiced"], l["clip"]) for l in doc["lines"]])
            # a line reworded afterwards, and not voiced again, is named
            first = doc["lines"][0]
            first["text"] = first["text"].replace("VoiceStudio", "VoiceStudio hôm nay", 1)
            self.assertEqual(make_video.stale_voices(doc, assets), [first["id"]])
            first["voiced"] = make_video.voiced_fingerprint(first["text"])
            self.assertEqual(make_video.stale_voices(doc, assets), [])
        # and the render command stops before any slow step
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "source").mkdir()
            (project / "source" / "draft-vi.json").write_text(json.dumps(fixture("voicestudio")), encoding="utf-8")
            shutil.copyfile(REPO / "scripts" / "radar" / "assets" / "gsap.min.js", project / "gsap.min.js")
            make_video.write_composition(project, plan, tl)
            args = type("Args", (), {"project": str(project), "videos_dir": tmp, "asr_python": None})()
            with self.assertRaises(SystemExit):
                make_video.cmd_render(args, project)

    def test_a_clip_swapped_for_another_lines_is_not_rendered(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        doc = make_video.voiceover_doc(plan, planlib.timeline(plan, estimated_durations(plan)))
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp)
            for line in doc["lines"]:
                (assets / f"{line['id']}.wav").write_bytes(f"clip of {line['id']}".encode())
                line["voiced"] = make_video.voiced_fingerprint(line["text"])
                line["clip"] = make_video.clip_fingerprint(assets / f"{line['id']}.wav")
            self.assertEqual(make_video.stale_voices(doc, assets), [])
            # the second line's file becomes a copy of the first line's: the words are the ones that were voiced, the clip is not
            shutil.copyfile(assets / "vo-1.wav", assets / "vo-2.wav")
            self.assertEqual(make_video.stale_voices(doc, assets), ["vo-2"])
            (assets / "vo-2.wav").unlink()                                                          # a clip that is gone is named too
            self.assertEqual(make_video.stale_voices(doc, assets), ["vo-2"])
            (assets / "vo-2.wav").write_bytes(b"clip of vo-2")                                      # the recorded file, back: fine
            self.assertEqual(make_video.stale_voices(doc, assets), [])
            del doc["lines"][2]["clip"]                                                             # a project voiced before clips were recorded
            self.assertEqual(make_video.stale_voices(doc, assets), [doc["lines"][2]["id"]])

    def test_a_digest_url_with_a_query_or_fragment_is_refused(self):
        for url in ("https://github.com/o/r?access_token=SECRET", "https://github.com/o/r#SECRET", "https://github.com/o/r?"):
            with self.assertRaises(ValueError) as caught:
                digest_with(lambda d: d["facts"].update(url=url))
            self.assertIn("facts.url", str(caught.exception))
            self.assertNotIn("SECRET", str(caught.exception))

    def test_a_percent_sign_after_a_space_is_read_like_one_without(self):
        self.assertEqual(numbers_vi.speak_text("giảm 19% và 19 % và -3 %"), "giảm mười chín phần trăm và mười chín phần trăm và âm ba phần trăm")
        self.assertEqual(numbers_vi.speak_text("tăng 2,5\u00a0%"), "tăng hai phẩy năm phần trăm")
        self.assertEqual(numbers_vi.speak_text("giảm 19 phần trăm"), "giảm mười chín phần trăm")
        self.assertEqual(numbers_vi.speak_text("100% và 100 % ."), "một trăm phần trăm và một trăm phần trăm .")
        # whatever spelling the gate counts as one value, the voice reads the same way
        for spellings in (("19%", "19 %", "19\u00a0%", "19 phần trăm"), ("-3,5%", "−3,5 %", "-3,5 phần trăm"),
                          ("62.958", "62,958"), ("-19", "−19")):
            self.assertEqual(len({check_facts.canonical(s) for s in spellings}), 1, spellings)
            self.assertEqual(len({numbers_vi.speak_text(s) for s in spellings}), 1, spellings)

    def test_a_grouped_number_longer_than_the_words_go_is_read_digit_by_digit(self):
        self.assertEqual(numbers_vi.speak_text("1.000.000.000.000 tham số"), " ".join(["một"] + ["không"] * 12) + " tham số")
        self.assertEqual(numbers_vi.speak_text("12,345,678,901,234"), "một hai ba bốn năm sáu bảy tám chín không một hai ba bốn")
        # the largest number with words, grouped or not, is still read as a number
        self.assertEqual(numbers_vi.speak_text("999.999.999.999"), numbers_vi.speak_text("999999999999"))
        self.assertTrue(numbers_vi.speak_text("999.999.999.999").startswith("chín trăm chín mươi chín tỷ"))
        # and nothing a digest can hold makes speak_text raise
        for digits in range(1, 30):
            numbers_vi.speak_text("9" * digits + " và " + ".".join(["999"] * (digits // 3 + 1)))

    def test_a_percent_sign_is_part_of_the_value(self):
        self.assertEqual(check_facts.numbers("giảm 19% và 19"), {"19%", "19"})
        self.assertEqual(check_facts.numbers("giảm 19 % và 19 phần trăm"), {"19%"})
        self.assertEqual(check_facts.numbers("tăng 2,5%, rồi -3%"), {"2.5%", "-3%"})
        source = check_facts.blob({"field": "giảm 19% so với 20"})
        self.assertEqual(check_facts.untraced("giảm 19% so với 20", source, set()), [])
        self.assertEqual(check_facts.untraced("giảm 19 phần trăm so với 20", source, set()), [])
        self.assertEqual(check_facts.untraced("giảm 19 so với 20", source, set()), ["number 19"])     # the unit cannot be dropped
        self.assertEqual(check_facts.untraced("giảm 20% so với 20", source, set()), ["number 20%"])    # nor added
        self.assertEqual(check_facts.untraced("giảm 19% so với 20.", source, set()), [])               # a full stop is not part of a number

    def test_a_remote_url_is_stored_without_its_credentials(self):
        self.assertEqual(make_video.without_credentials("https://user:ghp_SECRET@github.com/o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(make_video.without_credentials("https://x-access-token:abc@github.com/o/r"), "https://github.com/o/r")
        self.assertEqual(make_video.without_credentials("https://TOKEN@github.com/o/r"), "https://github.com/o/r")
        self.assertEqual(make_video.without_credentials("ssh://git@github.com/o/r.git"), "ssh://github.com/o/r.git")
        self.assertEqual(make_video.without_credentials("https://github.com/o/r"), "https://github.com/o/r")
        self.assertEqual(make_video.without_credentials("https://github.com:8443/o/r.git?access_token=SECRET"), "https://github.com:8443/o/r.git")
        self.assertEqual(make_video.without_credentials("https://github.com/o/r.git#SECRET"), "https://github.com/o/r.git")
        self.assertEqual(make_video.without_credentials("https://u:p@s@github.com/o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(make_video.without_credentials("git@github.com:o/r.git"), "github.com:o/r.git")          # scp-style: no user at all
        self.assertEqual(make_video.without_credentials("ghp_SECRET@github.com:o/r.git"), "github.com:o/r.git")
        self.assertEqual(make_video.without_credentials("github.com:o/r.git?x=SECRET"), "github.com:o/r.git")
        self.assertEqual(make_video.without_credentials("/srv/git/r.git"), "/srv/git/r.git")
        self.assertIsNone(make_video.without_credentials(None))
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "digests" / "d"
            repo.mkdir(parents=True)
            (repo / "draft-vi.json").write_text("{}", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "remote", "add", "origin", "https://user:ghp_SECRET@example.com/o/r.git"], check=True)
            came_from = make_video.where_it_came_from(repo / "draft-vi.json")
        self.assertEqual(came_from["git_remote"], "https://example.com/o/r.git")
        self.assertNotIn("SECRET", json.dumps(came_from))

    def test_the_report_that_a_standalone_render_created_accepts_a_later_voice_run(self):
        report = {"voice": {"voice": "Mai Anh"}}                       # what `render` writes when there is no report yet
        best = {"take": 2, "edits": 1, "ref_words": 10, "heard": "x"}
        voice = make_video.record_voice(report, "Mai Anh", 3, True, {"vo-1": best, "vo-2": {**best, "edits": 5}})
        self.assertEqual(voice["chosen"]["vo-1"]["wer"], 0.1)
        self.assertFalse(voice["chosen"]["vo-1"]["flagged"])
        self.assertTrue(voice["chosen"]["vo-2"]["flagged"])
        self.assertEqual((voice["voice"], voice["takes"], voice["asr"]), ("Mai Anh", 3, True))
        make_video.record_voice(report, "Mai Anh", 3, True, {"vo-3": best})   # a later partial run adds to what is there
        self.assertEqual(sorted(report["voice"]["chosen"]), ["vo-1", "vo-2", "vo-3"])
        unmeasured = make_video.record_voice({}, "Hải Đăng", 1, False, {"vo-1": {"take": 1, "edits": None, "ref_words": None, "heard": None}})
        self.assertIsNone(unmeasured["chosen"]["vo-1"]["wer"])


class Narration(unittest.TestCase):
    def test_reworded_lines_are_kept_and_judged_by_the_gate(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        step = next(l for l in doc["lines"] if l["unit"] == "step:1")
        step["text"] = "Phần backend tải mô hình tương ứng, rồi giao việc tính toán cho phần cứng phù hợp."
        step["source"] = ["draft.how_it_works.steps[1]"]
        kept = make_video.voiceover_doc(plan, tl, doc)
        self.assertEqual(next(l for l in kept["lines"] if l["unit"] == "step:1")["text"], step["text"])
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 1, "'giao' and 'cho' are Vietnamese words without diacritics; the project lists them in `allow`")
        doc["allow"] = ["giao", "cho"]
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 0, output)
        step["text"] += " Nhanh gấp 10 lần ElevenLabs."
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 1)
        self.assertIn("ElevenLabs", output)
        self.assertIn("number 10", output)

    def test_speak_always_follows_text(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "voicestudio.json"))
        tl = planlib.timeline(plan, estimated_durations(plan))
        doc = make_video.voiceover_doc(plan, tl)
        caveat = next(l for l in doc["lines"] if l["unit"] == "caveat:0")
        self.assertIn("ba chấm không", caveat["speak"])
        caveat.pop("speak")                          # a scaffold made before the AGPL-3.0 rule existed
        self.assertTrue(make_video.refresh_speak(doc))
        self.assertIn("ba chấm không", caveat["speak"])
        self.assertFalse(make_video.refresh_speak(doc))
        # a line reworded by hand: the old generated `speak` must not survive, or the old sentence would be read
        caveat["text"] = "Mã nguồn dùng giấy phép AGPL-3.0; còn trọng số có điều kiện riêng."
        self.assertTrue(make_video.refresh_speak(doc))
        self.assertEqual(caveat["speak"], "Mã nguồn dùng giấy phép AGPL ba chấm không; còn trọng số có điều kiện riêng.")
        kept = make_video.voiceover_doc(plan, tl, doc)
        self.assertEqual(next(l for l in kept["lines"] if l["unit"] == "caveat:0")["speak"], caveat["speak"])
        # a reworded line without digits has no `speak` at all
        step = next(l for l in doc["lines"] if l["unit"] == "step:1")
        step["text"], step["speak"] = "Chạy trong năm phút.", "Chạy trong 5 phút."
        make_video.refresh_speak(doc)
        self.assertNotIn("speak", step)

    def test_the_gate_refuses_a_speak_that_is_not_the_spelled_out_text(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        html = compose.render(plan, tl)
        doc = make_video.voiceover_doc(plan, tl)
        self.assertEqual(run_gate(digest, doc, html)[0], 0)
        line = next(l for l in doc["lines"] if l["unit"] == "step:0")
        line["speak"] = "ElevenLabs nhanh hơn chín mươi chín nghìn lần"
        status, output = run_gate(digest, doc, html)
        self.assertEqual(status, 1)
        self.assertIn(f"{line['id']}: `speak`", output)

    def test_the_narrator_named_in_the_report_is_the_one_in_readme_and_preview(self):
        digest = planlib.load_digest(FIXTURES / "voicestudio.json")
        plan = planlib.build_plan(digest)
        tl = planlib.timeline(plan, estimated_durations(plan))
        for voice, slug in (("Mai Anh", "mai-anh"), ("Hải Đăng", "hai-dang"), ("Thái Sơn", "thai-son")):
            report = {"voice": {"voice": voice}, "render": {"duration": 60.0, "check": "ok"}}
            with tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp) / "p"
                (project / "source").mkdir(parents=True)
                doc = make_video.write_composition(project, plan, tl)
                make_video.write_preview_json(project, plan, report)
                make_video.write_readme(project, plan, doc, report)
                preview = (project / "preview.json").read_text(encoding="utf-8")
                readme = (project / "README.md").read_text(encoding="utf-8")
            self.assertIn(voice, preview)
            self.assertIn(voice, readme)
            self.assertIn(f'"key": "{slug}"', preview)
            for other in {"Mai Anh", "Hải Đăng", "Thái Sơn"} - {voice}:
                self.assertNotIn(other, preview + readme)

    def test_speak_is_set_only_when_it_differs(self):
        plan = planlib.build_plan(planlib.load_digest(FIXTURES / "impeccable.json"))
        with_numbers = [u for u in plan["units"] if "speak" in u]
        self.assertTrue(with_numbers)
        for unit in with_numbers:
            self.assertNotEqual(unit["speak"], unit["text"])
            self.assertIsNone(re.search(r"(?<![\w\-.,])\d", unit["speak"]), unit["speak"])


if __name__ == "__main__":
    unittest.main()
