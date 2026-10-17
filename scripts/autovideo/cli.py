"""Command line of the batch video tool.

  python3 scripts/autovideo/main.py validate <pack>   check a pack: schema, files, TTS-unfriendly text. No network, no MPT.
  python3 scripts/autovideo/main.py plan <pack>       what would run: every job, its reading time, its MPT parameters, setup problems
  python3 scripts/autovideo/main.py run <pack>        render the jobs one after another (resumable)
  python3 scripts/autovideo/main.py status <pack>     what each job reached, checked against the files and the QA limits (exit 1 unless every video is done)
  python3 scripts/autovideo/main.py qa <pack>         run the QA again on rendered folders, without rendering
  python3 scripts/autovideo/main.py doctor            ffmpeg, ffprobe, the MPT checkout and which of its keys are set (never their values)

<pack> is a JSON file or a directory (pack.json + videos/<id>.json). Output goes to build/autovideo/<batch>/ (gitignored).
Exit codes: 0 all good, 1 a video failed, failed QA, is missing or stale (rendered from an older version of the pack), or `plan` finds a setup that
cannot run; 2 the pack or the arguments are wrong; 3 another run holds the batch (`run` and `qa` write its state). --json (plan, run, status) prints machine-readable output.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

from . import engine_mpt, qa, runner
from .pack import PackError, load_pack

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "build" / "autovideo"


def _retries(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {n}")
    return n


def _seconds(value: str) -> float:
    x = float(value)
    if not (math.isfinite(x) and x > 0):
        raise argparse.ArgumentTypeError(f"must be a positive number of seconds, got {value!r}")
    return x


def _load(args):
    try:
        pack = load_pack(args.pack, check_files=True)
    except PackError as exc:
        print(f"{args.pack}: {len(exc.problems)} problem(s)", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(2)
    for warning in pack.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return pack


def _env(args):
    try:
        return engine_mpt.locate(args.mpt_home, args.mpt_python)
    except engine_mpt.MptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)


def cmd_validate(args) -> int:
    pack = _load(args)
    print(f"{pack.batch}: {len(pack.jobs)} video(s) valid, {len(pack.warnings)} warning(s)")
    return 0


def cmd_plan(args) -> int:
    pack = _load(args)
    setup_problem = None
    try:
        env = engine_mpt.locate(args.mpt_home, args.mpt_python)
    except engine_mpt.MptError as exc:
        env, setup_problem = None, str(exc)  # `run` cannot start either, so the plan is not ready; the reason is part of the answer
    plan = []
    for job in pack.jobs:
        plan.append({
            "id": job.id, "title": job.title, "scenes": len(job.scenes), "estimated_seconds": job.estimate_seconds(),
            "target_seconds": [job.min_seconds, job.max_seconds], "aspect": job.aspect, "language": job.language,
            "voice": job.audio_file or job.voice, "source": job.material_source, "terms": list(job.terms),
            "problem": runner.preflight(env, job) if env else setup_problem,
            "mpt_params": engine_mpt.video_params(job),
        })
    blocked = any(p["problem"] for p in plan)
    if args.json:
        print(json.dumps({"batch": pack.batch, "videos": plan}, ensure_ascii=False, indent=2))
        return 1 if blocked else 0
    print(f"batch {pack.batch}: {len(plan)} video(s), rendered one at a time into {Path(args.out) / pack.batch}")
    for p in plan:
        print(f"  {p['id']}: {p['title']} | {p['scenes']} scenes, ~{p['estimated_seconds']:g} s (target {p['target_seconds'][0]:g}-{p['target_seconds'][1]:g}) "
              f"| {p['aspect']} | {p['voice']} | {p['source']}" + (f" | CANNOT RUN: {p['problem']}" if p["problem"] else ""))
    return 1 if blocked else 0


def cmd_run(args) -> int:
    pack = _load(args)
    env = _env(args)
    only = [i for i in (args.only or "").split(",") if i]
    try:
        summary = runner.run(
            pack, env, Path(args.out), only=only, force=args.force, retries=args.retries, timeout=args.timeout,
            log=lambda line: print(line, file=sys.stderr),
        )
    except runner.BatchBusy as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else
          f"{summary['batch']}: {summary['done']} done, {summary['skipped']} skipped, {summary['failed']} failed, "
          f"{summary['qa_failed']} failed QA -> {summary['output']}")
    return 1 if summary["failed"] or summary["qa_failed"] else 0


def _env_if_any(args):
    """The MPT checkout when it can be found, else None: `status` and `qa` work without it, but then cannot look at the music file."""
    try:
        return engine_mpt.locate(args.mpt_home, args.mpt_python)
    except engine_mpt.MptError:
        return None


def cmd_status(args) -> int:
    pack = _load(args)
    state = runner.read_state(Path(args.out) / pack.batch)["jobs"]
    env = _env_if_any(args)
    rows = []
    for job in pack.jobs:
        entry = state.get(job.id)
        status = runner.job_status(entry, job, Path(args.out) / pack.batch / job.id, engine_mpt.input_digests(env, job) if env else None)
        rows.append({"id": job.id, "status": status, "attempts": (entry or {}).get("attempts", 0), "error": (entry or {}).get("error")})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"{r['id']}: {r['status']}" + (f" ({r['error']})" if r["error"] else ""))
    return 0 if all(r["status"] == "done" for r in rows) else 1  # anything but done is "not ready": pending, stale, missing, unchecked, failed


def cmd_qa(args) -> int:
    pack = _load(args)
    try:
        rows = runner.requalify(pack, Path(args.out), [i for i in (args.only or "").split(",") if i], _env_if_any(args))
    except runner.BatchBusy as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for r in rows:
        print(f"{r['id']}: {r['status']}")
        for c in r["checks"]:
            if not c["ok"]:
                print(f"    {c['level']}: {c['name']}: {c['detail']}")
    return 1 if any(r["status"] != "done" for r in rows) else 0  # a video that was missing or stale was not checked


def cmd_doctor(args) -> int:
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        ok &= bool(found)
        print(f"{tool}: {found or 'NOT FOUND'}")
    try:
        env = engine_mpt.locate(args.mpt_home, args.mpt_python)
    except engine_mpt.MptError as exc:
        print(f"MoneyPrinterTurbo: {exc}")
        return 1
    print(f"MoneyPrinterTurbo: {env.home} (runs with: {' '.join(env.python)})")
    for name, value in engine_mpt.doctor_info(env).items():
        print(f"  {name}: {'set' if value is True else 'NOT set' if value is False else value or '(empty)'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autovideo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, pack=True, json_output=False):
        if pack:
            p.add_argument("pack", help="pack JSON file, or directory with pack.json and videos/")
        p.add_argument("--out", default=str(DEFAULT_OUT), help="output root (default: %(default)s)")
        p.add_argument("--mpt-home", help="MoneyPrinterTurbo checkout (default: $MPT_HOME, then ~/MoneyPrinterTurbo)")
        p.add_argument("--mpt-python", help="Python that runs MPT's cli.py (default: $MPT_PYTHON, then <mpt-home>/.venv, then uv run)")
        if json_output:
            p.add_argument("--json", action="store_true", help="print machine-readable output")

    for name, fn, text in (
        ("validate", cmd_validate, "check a pack"), ("plan", cmd_plan, "show what would run"), ("run", cmd_run, "render the jobs"),
        ("status", cmd_status, "show how far each job got"), ("qa", cmd_qa, "run QA again on rendered folders"),
    ):
        p = sub.add_parser(name, help=text)
        common(p, json_output=name in ("plan", "run", "status"))
        p.set_defaults(fn=fn)
        if name in ("run", "qa"):
            p.add_argument("--only", help="comma-separated video ids")
        if name == "run":
            p.add_argument("--force", action="store_true", help="render again even when a job is done and unchanged")
            p.add_argument("--retries", type=_retries, default=1, help="extra attempts for a job that fails or fails QA (default: %(default)s)")
            p.add_argument("--timeout", type=_seconds, default=1800, help="seconds MPT may take for one job (default: %(default)s)")
    p = sub.add_parser("doctor", help="check the setup")
    common(p, pack=False)
    p.set_defaults(fn=cmd_doctor)

    args = parser.parse_args(argv)
    return args.fn(args)
