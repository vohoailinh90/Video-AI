"""Tests for the radar-digest-to-video scripts: no network, no model, no browser.

    python3 -m unittest discover -s tests -v

Fixtures are real digests (draft-vi.json) copied from the github-radar repository: a typical one (voicestudio), one without try_it
(moneyprinterturbo), one whose problem is a single sentence (orca) and the longest one (impeccable).
"""
import copy
import json
import re
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


def run_gate(digest, doc, html):
    """check_facts.py as a subprocess, the way make_video.py runs it. Returns (exit status, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
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
