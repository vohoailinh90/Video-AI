"""Render the HyperFrames composition (index.html) of a radar video from its plan and timeline.

A pure function: the same plan and timings always give the same file. Every string a viewer reads is either a field of the digest
(escaped, never reworded) or a fixed label of this file, marked data-label so scripts/vo/check_facts.py leaves it out of the trace.
All animation is a flat list of GSAP calls at absolute times, so no timing logic runs inside the composition.

Look and motion follow videos/demo-video and videos/voicestudio (dark grid, orange accent, 1920x1080, 30 fps).
"""
import html as htmllib
import json

import plan as planlib
from check_facts import FIXED_LABELS

E = htmllib.escape

LABELS = FIXED_LABELS   # the gate owns the list of fixed words it lets through

CSS = """
      * { margin: 0; padding: 0; box-sizing: border-box; }
      :root {
        --bg: #0b0c10; --ink: #f4f4f5; --muted: #9ca3af; --accent: #ff9d2e;
        --accent-soft: rgba(255, 157, 46, 0.14); --mint: #5eead4; --line: rgba(255, 255, 255, 0.12);
      }
      html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: var(--bg); }
      #root { position: relative; width: 100%; height: 100%; overflow: hidden; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: var(--ink); }
      .bg-grid {
        background:
          radial-gradient(ellipse 70% 60% at 50% 38%, rgba(255, 157, 46, 0.16), transparent 70%),
          linear-gradient(var(--line) 1px, transparent 1px) 0 0 / 96px 96px,
          linear-gradient(90deg, var(--line) 1px, transparent 1px) 0 0 / 96px 96px,
          var(--bg);
      }
      .stage { position: absolute; inset: 0; padding: 88px 120px; display: flex; flex-direction: column; justify-content: center; }
      .tag { font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 28px; letter-spacing: 0.16em; color: var(--accent); overflow-wrap: anywhere; }
      h1.big { font-weight: 800; line-height: 1.02; letter-spacing: -0.045em; margin-top: 24px; }
      h1.big .line { display: block; overflow: hidden; padding-bottom: 14px; }
      h1.big .line > span { display: block; overflow-wrap: anywhere; }
      .sub { font-size: 52px; color: var(--muted); margin-top: 30px; font-weight: 500; max-width: 1560px; line-height: 1.25; }
      .chips { display: flex; flex-wrap: wrap; gap: 22px; margin-top: 56px; }
      .chip { border: 2px solid var(--line); border-radius: 999px; padding: 16px 34px; font-size: 36px; font-weight: 650; background: rgba(255, 255, 255, 0.05); }
      .chip b { color: var(--accent); font-weight: 800; }
      .scan { margin-top: 34px; font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 26px; letter-spacing: 0.08em; color: var(--muted); }
      h2.head { font-size: 88px; font-weight: 800; letter-spacing: -0.035em; margin-top: 16px; line-height: 1.08; }

      .problem { display: flex; align-items: center; gap: 36px; margin-top: 64px; }
      .pains { display: flex; flex-direction: column; gap: 24px; width: 880px; flex: none; }
      .pain { border: 2px solid var(--line); border-radius: 24px; padding: 28px 40px; font-weight: 650; line-height: 1.25;
        background: linear-gradient(160deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.02)); overflow-wrap: anywhere; }
      .link { position: relative; width: 110px; height: 6px; flex: none; }
      .link i { position: absolute; inset: 0; background: var(--accent); border-radius: 3px; transform-origin: left center; }
      .link::after { content: ""; position: absolute; right: -2px; top: -12px; border-left: 26px solid var(--accent);
        border-top: 15px solid transparent; border-bottom: 15px solid transparent; opacity: var(--tip, 0); }
      .solution { flex: 1; min-width: 0; min-height: 360px; border: 2px solid var(--accent); border-radius: 28px; padding: 44px 48px;
        background: linear-gradient(160deg, var(--accent-soft), rgba(255, 157, 46, 0.03)); display: flex; flex-direction: column; justify-content: center; }
      .solution small { font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 26px; letter-spacing: 0.16em; color: var(--accent); overflow-wrap: anywhere; }
      .solution strong { line-height: 1.18; font-weight: 760; letter-spacing: -0.025em; margin-top: 20px; overflow-wrap: anywhere; }

      .flow { display: flex; align-items: center; margin-top: 60px; }
      .node { flex: 1 1 0; min-width: 0; height: 210px; border-radius: 28px; border: 2px solid var(--line);
        background: linear-gradient(160deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));
        display: flex; align-items: center; padding: 0 32px; font-weight: 740; letter-spacing: -0.02em; line-height: 1.18; overflow-wrap: anywhere; }
      .node.last { border-color: var(--accent); background: linear-gradient(160deg, var(--accent-soft), rgba(255, 157, 46, 0.03)); }
      .arrow { position: relative; flex: 0 0 72px; height: 6px; }
      .arrow i { position: absolute; inset: 0 12px 0 0; background: var(--accent); border-radius: 3px; transform-origin: left center; }
      .arrow::after { content: ""; position: absolute; right: -2px; top: -12px; border-left: 26px solid var(--accent);
        border-top: 15px solid transparent; border-bottom: 15px solid transparent; opacity: var(--tip, 0); }
      .parts-title { margin-top: 56px; font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 28px; letter-spacing: 0.16em; color: var(--accent); }
      .parts { display: flex; flex-wrap: wrap; gap: 24px; margin-top: 20px; }
      .part { flex: 1 1 380px; min-width: 0; border: 2px solid var(--line); border-radius: 22px; padding: 24px 32px; background: rgba(255, 255, 255, 0.04); }
      .part strong { display: block; font-size: 38px; font-weight: 750; letter-spacing: -0.02em; overflow-wrap: anywhere; }
      .part span { display: block; margin-top: 10px; font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 26px; line-height: 1.4; color: var(--mint); overflow-wrap: anywhere; }

      .lessons { display: flex; gap: 36px; margin-top: 64px; }
      .lesson { flex: 1 1 0; min-width: 0; border: 2px solid var(--line); border-radius: 28px; padding: 44px 42px; min-height: 400px;
        background: linear-gradient(160deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.02)); display: flex; flex-direction: column; justify-content: center; }
      .lesson p { line-height: 1.24; font-weight: 700; letter-spacing: -0.02em; overflow-wrap: anywhere; }

      .cols { display: flex; gap: 56px; margin-top: 28px; }
      .col { flex: 1 1 0; min-width: 0; }
      .col h2.head { font-size: 72px; margin-top: 0; }
      .caveat { margin-top: 26px; border: 2px solid var(--line); border-left: 8px solid var(--accent); border-radius: 22px; padding: 26px 32px;
        line-height: 1.34; background: rgba(255, 255, 255, 0.04); overflow-wrap: anywhere; }
      .term { margin-top: 26px; border: 2px solid var(--line); border-radius: 24px; background: #111318; overflow: hidden; }
      .term .top { height: 56px; border-bottom: 2px solid var(--line); display: flex; align-items: center; gap: 14px; padding: 0 26px; }
      .term .top i { width: 16px; height: 16px; border-radius: 50%; background: #3a3f4a; }
      .term .body { padding: 30px 40px 34px; font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 38px; line-height: 1.75; }
      .term .prompt { color: var(--accent); }
      .term .cmd { display: inline-block; max-width: 100%; overflow-wrap: anywhere; white-space: pre-wrap; }
      .note { margin-top: 22px; font-size: 28px; line-height: 1.38; color: var(--muted); overflow-wrap: anywhere; }
      .foot { position: absolute; left: 120px; bottom: 56px; font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 28px; letter-spacing: 0.08em; color: var(--muted); }
"""


def num(x) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def size_by_length(text, steps):
    """steps: [(max_chars, px), ...] ascending, the last px is the fallback."""
    for limit, px in steps[:-1]:
        if len(text) <= limit:
            return px
    return steps[-1][1]


class Script:
    def __init__(self):
        self.lines = []

    def rise(self, selector, at, dur=0.55):
        self.lines.append(f"rise({json.dumps(selector)}, {num(at)}, {num(dur)});")

    def pop(self, selector, at):
        self.lines.append(f"pop({json.dumps(selector)}, {num(at)});")

    def draw(self, selector, at):
        self.lines.append(f"draw({json.dumps(selector)}, {num(at)});")

    def raw(self, text):
        self.lines.append(text)

    def fade_out(self, selector, end):
        self.lines.append(f"fadeOut({json.dumps(selector)}, {num(end)});")


def cover_scene(plan, scene, n, js):
    sid, start = f"s{n}", scene["start"]
    size = max(96, min(220, int(2900 / max(len(plan["name"]), 1))))
    chips = []
    for i, chip in enumerate(plan["chips"]):
        if chip["label"]:
            label = LABELS["stars"] if chip["label"] == "sao" else LABELS["forks"]
            chips.append(f'<div class="chip" id="{sid}-c{i}"><b>{E(chip["value"])}</b> <span data-label>{E(label)}</span></div>')
        else:
            chips.append(f'<div class="chip" id="{sid}-c{i}">{E(chip["value"])}</div>')
    scan = (f'<div class="scan" id="{sid}-scan"><span data-label>{E(LABELS["scan"])}</span> {E(plan["scan"])}</div>' if plan["scan"] else "")
    markup = f"""
      <!-- scene {n}: name and numbers -->
      <section id="{sid}" class="clip" data-start="{num(start)}" data-duration="{num(scene['end'] - start)}" data-track-index="1">
        <div class="stage" id="{sid}-in">
          <div class="tag" id="{sid}-tag">{E(plan['full_name'])}</div>
          <h1 class="big" style="font-size:{size}px"><span class="line"><span id="{sid}-name">{E(plan['name'])}</span></span></h1>
          <div class="sub" id="{sid}-sub">{E(plan['subtitle'])}</div>
          <div class="chips">{''.join(chips)}</div>
          {scan}
        </div>
      </section>"""
    js.rise(f"#{sid}-tag", start + 0.15, 0.5)
    js.raw(f'tl.fromTo("#{sid}-name", {{ yPercent: 110 }}, {{ yPercent: 0, duration: 0.8, ease: "expo.out" }}, {num(start + 0.3)});')
    js.rise(f"#{sid}-sub", start + 1.0, 0.6)
    for i in range(len(plan["chips"])):
        js.pop(f"#{sid}-c{i}", start + 2.0 + 0.35 * i)
    if plan["scan"]:
        js.rise(f"#{sid}-scan", start + 2.2 + 0.35 * len(plan["chips"]), 0.6)
    return markup


def problem_scene(plan, scene, clips, n, js):
    sid, start = f"s{n}", scene["start"]
    items = plan["problem"]
    pains, solution = (items[:-1], items[-1]) if len(items) > 1 else ([], items[0])
    pain_html = "".join(
        f'<div class="pain" id="{sid}-p{i}" style="font-size:{size_by_length(p["text"], [(80, 42), (140, 38), (220, 34), (999, 30)])}px">{E(p["text"])}</div>'
        for i, p in enumerate(pains))
    link = f'<div class="link" id="{sid}-lk"><i></i></div>' if pains else ""
    sol_px = size_by_length(solution["text"], [(90, 54), (150, 46), (999, 38)])
    markup = f"""
      <!-- scene {n}: the problem -->
      <section id="{sid}" class="clip" data-start="{num(start)}" data-duration="{num(scene['end'] - start)}" data-track-index="1">
        <div class="stage" id="{sid}-in">
          <div class="tag" id="{sid}-tag">{E(plan['name'])}</div>
          <h2 class="head" id="{sid}-head" data-label>{E(LABELS['problem'])}</h2>
          <div class="problem">
            {'<div class="pains">' + pain_html + '</div>' if pains else ''}
            {link}
            <div class="solution" id="{sid}-sol">
              <small>{E(plan['name'])}</small>
              <strong style="font-size:{sol_px}px">{E(solution['text'])}</strong>
            </div>
          </div>
        </div>
      </section>"""
    js.rise(f"#{sid}-tag", start + 0.1, 0.45)
    js.rise(f"#{sid}-head", start + 0.25, 0.6)
    for i, p in enumerate(pains):
        js.pop(f"#{sid}-p{i}", clips[p["uid"]]["start"] - 0.2)
    if pains:
        js.raw(f'tl.fromTo("#{sid}-lk i", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.5, ease: "power2.inOut" }}, {num(clips[solution["uid"]]["start"] - 0.65)});')
        js.raw(f'tl.fromTo("#{sid}-lk", {{ "--tip": 0 }}, {{ "--tip": 1, duration: 0.1 }}, {num(clips[solution["uid"]]["start"] - 0.2)});')
    js.pop(f"#{sid}-sol", clips[solution["uid"]]["start"] - 0.2)
    return markup


def how_scene(plan, scene, clips, n, js):
    sid, start = f"s{n}", scene["start"]
    steps, count = plan["steps"], len(plan["steps"])
    px = 40 if count <= 3 else 36 if count == 4 else 32
    flow = []
    for i, step in enumerate(steps):
        cls = "node last" if i == count - 1 else "node"
        flow.append(f'<div class="{cls}" id="{sid}-n{i}" style="font-size:{px}px">{E(step["title"])}</div>')
        if i < count - 1:
            flow.append(f'<div class="arrow" id="{sid}-a{i}"><i></i></div>')
    parts_html = ""
    if plan["components"]:
        chips = "".join(      # a space between the two blocks: the gate reads text that touches in the markup as touching on the screen
            f'<div class="part" id="{sid}-pt{i}"><strong>{E(c["name"])}</strong>' + (f' <span>{E(c["evidence"])}</span>' if c["evidence"] else "") + "</div>"
            for i, c in enumerate(plan["components"]))
        parts_html = f'<div class="parts-title" id="{sid}-parts-title" data-label>{E(LABELS["parts"])}</div><div class="parts">{chips}</div>'
    markup = f"""
      <!-- scene {n}: how it works -->
      <section id="{sid}" class="clip" data-start="{num(start)}" data-duration="{num(scene['end'] - start)}" data-track-index="1">
        <div class="stage" id="{sid}-in">
          <div class="tag" id="{sid}-tag">{E(plan['name'])}</div>
          <h2 class="head" id="{sid}-head" data-label>{E(LABELS['how'])}</h2>
          <div class="flow">{''.join(flow)}</div>
          {parts_html}
        </div>
      </section>"""
    js.rise(f"#{sid}-tag", start + 0.1, 0.45)
    js.rise(f"#{sid}-head", start + 0.25, 0.6)
    for i, step in enumerate(steps):
        at = clips[step["uid"]]["start"] - 0.2
        js.raw(f'tl.fromTo("#{sid}-n{i}", {{ opacity: 0, scale: 0.92 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "back.out(1.5)" }}, {num(at)});')
        if i > 0:
            js.draw(f"#{sid}-a{i - 1}", at - 0.4)
    if plan["components"]:
        after = clips[steps[-1]["uid"]]["end"] + 0.4
        js.rise(f"#{sid}-parts-title", after, 0.5)
        for i in range(len(plan["components"])):
            js.rise(f"#{sid}-pt{i}", after + 0.3 + 0.3 * i, 0.55)
    return markup


def learn_scene(plan, scene, clips, n, js):
    sid, start = f"s{n}", scene["start"]
    longest = max(len(item["text"]) for item in plan["learn"])
    px = size_by_length("x" * longest, [(70, 44), (110, 38), (999, 32)])
    cards = "".join(f'<div class="lesson" id="{sid}-l{i}"><p style="font-size:{px}px">{E(item["text"])}</p></div>' for i, item in enumerate(plan["learn"]))
    markup = f"""
      <!-- scene {n}: what to learn -->
      <section id="{sid}" class="clip" data-start="{num(start)}" data-duration="{num(scene['end'] - start)}" data-track-index="1">
        <div class="stage" id="{sid}-in">
          <div class="tag" id="{sid}-tag">{E(plan['name'])}</div>
          <h2 class="head" id="{sid}-head" data-label>{E(LABELS['learn'])}</h2>
          <div class="lessons">{cards}</div>
        </div>
      </section>"""
    js.rise(f"#{sid}-tag", start + 0.1, 0.45)
    js.rise(f"#{sid}-head", start + 0.25, 0.6)
    for i, item in enumerate(plan["learn"]):
        js.pop(f"#{sid}-l{i}", clips[item["uid"]]["start"] - 0.2)
    return markup


def end_scene(plan, scene, clips, n, js):
    sid, start = f"s{n}", scene["start"]
    caveats, try_it = plan["caveats"], plan["try"]
    left = right = ""
    if caveats:
        cards = "".join(
            f'<div class="caveat" id="{sid}-cv{i}" style="font-size:{size_by_length(c["text"], [(110, 33), (150, 30), (999, 27)])}px">{E(c["text"])}</div>'
            for i, c in enumerate(caveats))
        left = f'<div class="col"><h2 class="head" id="{sid}-head-l" data-label>{E(LABELS["caveats"])}</h2>{cards}</div>'
    if try_it:
        term = ""
        if try_it["commands"]:
            rows = "".join(f'<div class="row"><span class="prompt">$</span> <span class="cmd" id="{sid}-cmd{i}">{E(c)}</span></div>'
                           for i, c in enumerate(try_it["commands"]))
            px = 38 if len(try_it["commands"]) <= 4 else 32
            term = (f'<div class="term" id="{sid}-term"><div class="top"><i></i><i></i><i></i></div>'
                    f'<div class="body" style="font-size:{px}px">{rows}</div></div>')
        note = f'<div class="note" id="{sid}-note">{E(try_it["note"])}</div>' if try_it["note"] else ""
        right = f'<div class="col"><h2 class="head" id="{sid}-head-r" data-label>{E(LABELS["try"])}</h2>{term}{note}</div>'
    markup = f"""
      <!-- scene {n}: caveats and try it -->
      <section id="{sid}" class="clip" data-start="{num(start)}" data-duration="{num(scene['end'] - start)}" data-track-index="1">
        <div class="stage" id="{sid}-in">
          <div class="tag" id="{sid}-tag">{E(plan['name'])}</div>
          <div class="cols">{left}{right}</div>
        </div>
        <div class="foot" id="{sid}-foot">{E(plan['url_text'])}</div>
      </section>"""
    js.rise(f"#{sid}-tag", start + 0.1, 0.45)
    if caveats:
        js.rise(f"#{sid}-head-l", start + 0.25, 0.6)
        for i, c in enumerate(caveats):
            js.rise(f"#{sid}-cv{i}", clips[c["uid"]]["start"] - 0.2, 0.6)
    if try_it:
        head_at = planlib.terminal_head_at(plan, clips, start)
        js.rise(f"#{sid}-head-r", head_at, 0.6)
        if try_it["commands"]:
            js.raw(f'tl.fromTo("#{sid}-term", {{ opacity: 0, y: 36 }}, {{ opacity: 1, y: 0, duration: 0.55, ease: E }}, {num(head_at + 0.3)});')
            for i in range(len(try_it["commands"])):
                js.raw(f'tl.fromTo("#{sid}-cmd{i}", {{ clipPath: "inset(0 100% 0 0)" }}, {{ clipPath: "inset(0 0% 0 0)", duration: 0.5, ease: "steps(12)" }}, {num(planlib.terminal_command_at(head_at, i))});')
        if try_it["note"]:
            js.rise(f"#{sid}-note", (clips[try_it["uid"]]["start"] - 0.1) if try_it["uid"] else head_at + 0.5, 0.6)
    js.rise(f"#{sid}-foot", start + 0.8, 0.6)
    return markup


def render(plan, tl) -> str:
    clips = tl["clips"]
    js = Script()
    scenes_html = []
    last = len(tl["scenes"]) - 1
    for index, scene in enumerate(tl["scenes"]):
        n = index + 1
        kind = scene["id"]
        if kind == "cover":
            scenes_html.append(cover_scene(plan, scene, n, js))
        elif kind == "problem":
            scenes_html.append(problem_scene(plan, scene, clips, n, js))
        elif kind == "how":
            scenes_html.append(how_scene(plan, scene, clips, n, js))
        elif kind == "learn":
            scenes_html.append(learn_scene(plan, scene, clips, n, js))
        else:
            scenes_html.append(end_scene(plan, scene, clips, n, js))
        if index < last:
            js.fade_out(f"#s{n}-in", scene["end"])

    total = num(tl["duration"])
    audio = "\n".join(
        f'      <audio id="{u["id"]}" src="assets/{u["id"]}.wav" data-start="{num(clips[u["id"]]["start"])}" '
        f'data-duration="{num(clips[u["id"]]["end"] - clips[u["id"]]["start"] + 0.01)}" data-track-index="{10 + i}" data-volume="1"></audio>'
        for i, u in enumerate(plan["units"]))
    return f"""<!doctype html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="gsap.min.js"></script>
    <style>{CSS}    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1920" data-height="1080">
      <div id="bg" class="clip bg-grid" data-start="0" data-duration="{total}" data-track-index="0"></div>

      <!-- music bed (assets/pad.wav, made with ffmpeg by scripts/radar/make_video.py) -->
      <audio id="music-bed" src="assets/pad.wav" data-start="0" data-duration="{total}" data-track-index="9" data-volume="0.6"></audio>

      <!-- Vietnamese narration. start, duration and volume are written by scripts/vo/revoice.py from voiceover.json -->
{audio}
{''.join(scenes_html)}
    </div>

    <script>
      const tl = gsap.timeline({{ paused: true }});
      const E = "power3.out";
      const fadeOut = (sel, end) => tl.to(sel, {{ opacity: 0, y: -18, duration: 0.35, ease: "power2.in" }}, end - 0.35);
      const rise = (sel, at, dur) => tl.fromTo(sel, {{ opacity: 0, y: 24 }}, {{ opacity: 1, y: 0, duration: dur, ease: E }}, at);
      const pop = (sel, at) => tl.fromTo(sel, {{ opacity: 0, y: 50, scale: 0.96 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.65, ease: "back.out(1.3)" }}, at);
      const draw = (arrow, at) => {{
        tl.fromTo(arrow + " i", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.4, ease: "power2.inOut" }}, at);
        tl.fromTo(arrow, {{ "--tip": 0 }}, {{ "--tip": 1, duration: 0.1 }}, at + 0.35);
      }};

{chr(10).join('      ' + line for line in js.lines)}

      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
