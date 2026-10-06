"""SoHoT: generate media and talk to the machine, all locally.

    soh image "a red fox in snow" --width 768
    soh video "a fox running" --seconds 2
    soh svg   "a settings gear icon"
    soh web   "a landing page for a coffee roaster"
    soh code  "a python function that parses an ISO timestamp"
    soh extract --file build.log "how many tests failed?"
    soh say   "bonjour" --voice fr-male
    soh voices
    soh hear  --seconds 5

Every command is blocking, because on this hardware everything except video
finishes in around a second: images take about a minute, speech is sub-second.
Video is the exception and it streams its progress rather than going quiet for
forty minutes. There is deliberately no job dispatcher.

Exit status is 0 only when a usable artifact exists. "The command exited 0" is
not evidence: a broken diffusion pipeline emits a uniform grey square at the
right resolution with a clean exit status, so the output is checked before this
reports success.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import time
import sys
from pathlib import Path

from harness.checks import code as code_check
from harness import (audio, completion, discover as discovery, env, exclusive,
                     lanes, memory, paths, proc, reasons, vector)
from harness.checks import html as html_check
from harness.checks import image as image_check
from harness.checks import svg as svg_check
from harness.engines import resolve

DEFAULT_IMAGE_ENGINE = "mflux:flux2-klein-4b"
DEFAULT_VIDEO_ENGINE = "h3"
#: The music lane's incumbent. Turbo at 8 steps rather than the base model:
#: it is what was measured on this machine (issue #236) and the base model's
#: 32-100 steps have never been run here.
DEFAULT_MUSIC_ENGINE = "acestep:acestep-v15-turbo"

# Every evals/cases/{image,video}/*.yaml pins a resolution. The CLI did not, so
# it inherited whatever each engine defaults to -- 1024 for mflux -- and ran a
# different exam from the suite that chose its engine, which is how two correct
# measurements came to look like a regression (#157, #141, #142). Named rather
# than inlined so tests/test_cli_resolution.py can hold the two to each other.
DEFAULT_RESOLUTION = 512
# Per-lane defaults, set from the eval of 2026-09-06 rather than from a tier
# name. NO SINGLE MODEL WINS ALL FOUR LANES, so there is no one default to
# pick.
#
# EVERY NUMBER BELOW IS FROM ONE EXAM: an M2 Pro with 32 GB, mlx_lm.server
# behind the LiteLLM gateway, DEFAULT_TEMPERATURE 0.2, 2026-09-06. None of it
# has been re-run on a discrete card (#96), and a different temperature is a
# different exam (#90). Re-derive with:
#   uv run python -m evals.run --modality <lane> --repeat 3 \
#     --candidates local-mid,local-large,q3-4b,q3-8b,q3-14b
#
#   lane     winner       runner-up            why
#   svg      local-large  q3-14b               7/9 both; 4.7s vs 10.0s
#   web      q3-4b        local-large          5/5 vs 3/5 at 21.5s vs 19.1s
#
# svg and web had ONE default until the web lane was widened from two cases to
# five. At two cases local-large and q3-4b both scored 6/6, the lane
# discriminated nothing, and speed decided. At five they separate cleanly and
# they separate the OTHER WAY from svg -- so a single default could only ever
# have been wrong for one of the two lanes.
#
# q3-14b scores marginally better ink on both and is NOT used, because it is a
# hybrid THINKING model: it answers "reply with exactly: OK" in 152 completion
# tokens against 2, and on a real SVG it spends the entire budget reasoning and
# returns null content. `lh svg` timed out twice at 180s on it. q3-8b is worse
# still: 0/9 on svg, every run a timeout. The eval's pass rate and median hid
# this, because an aggregate does not show you HOW the failures fail.
#   code     q3-4b        q3-8b                6/9 both; 2.9s vs 130s
#   extract  local-large  q3-14b               9/10 both; 0.79s vs 13.4s
#
# Qwen2.5-7B (local-large) KEEPS the extract lane on merit: same accuracy as
# Qwen3-14B at seventeen times the speed. Being a generation behind did not
# make it wrong for a job that is one short answer from a log.
#
# Qwen2.5-1.5B (local-mid) was the default for svg and web and scored 2/9 and
# 3/6. That was the single worst consequence of never having compared anything.
DEFAULT_SVG_MODEL = "local-large"
DEFAULT_WEB_MODEL = "q3-4b"
DEFAULT_CODE_MODEL = "q3-4b"
DEFAULT_EXTRACT_MODEL = "local-large"
# Typed by hand, not measured: the code lane's default as the decide baseline. #423.
DEFAULT_DECIDE_MODEL = "q3-4b"

# Named per engine family because the fix differs, and because `uv tool install
# mflux` on its own silently picks Python 3.9, where every mflux entry point
# dies on `int | None`. The tell is 2 executables installed instead of 37.
INSTALL_HINT = {
    "mflux": " Install it with: uv tool install --python 3.12 mflux",
    "h3": " Build it: git clone https://github.com/antirez/h3.c && make -C h3.c",
}


#: Set by main() from --json. A module global because every verb reports
#: through err()/say(), and threading a flag through nine functions to reach
#: two print statements is worse than this.
_JSON = False
_VERB = ""


def err(msg: str) -> int:
    """Report a failure. Under --json it is DATA on stdout, not a stderr line.

    An agent that has to read stderr to discover something went wrong will not
    read stderr. The exit code stays 1 either way.
    """
    if _JSON:
        print(json.dumps({"ok": False, "verb": _VERB, "error": msg}))
    else:
        print(msg, file=sys.stderr)
    return 1


def say(*, path=None, body=None, seconds=None, peak_kb=None, size=None,
        human: str = "") -> int:
    """Report a success, in whichever shape the caller asked for."""
    if _JSON:
        out = {"ok": True, "verb": _VERB}
        if path is not None:
            out["path"] = str(path)
        if body is not None:
            out["body"] = body
        if seconds is not None:
            out["seconds"] = round(seconds, 3)
        if peak_kb:
            out["peak_gib"] = round(peak_kb / 1024 / 1024, 2)
        if size is not None:
            out["size"] = size
        print(json.dumps(out))
    else:
        print(human)
    return 0


def note(*args, **kw) -> None:
    """Human text. Under --json it goes to stderr so stdout stays one object."""
    print(*args, file=sys.stderr if _JSON else sys.stdout, **kw)


def emit(ok: bool = True, **data) -> None:
    """Under --json, the verb's result as one object on stdout. #329."""
    if _JSON:
        print(json.dumps({"ok": ok, "verb": _VERB, **data}, default=str))


def default_output(kind: str, suffix: str) -> Path:
    """Where an artifact goes when the caller did not say.

    Under $LOCALHARNESS_HOME/out, which is ABSOLUTE. It used to be a relative
    `out/`, and since `lh` installs onto PATH and runs from anywhere, that
    scattered artifacts into whatever directory the caller happened to be
    standing in.
    """
    return paths.artifact(kind, suffix)


def _generate(spec: str, prompt: str, out: Path, params: dict) -> int:
    """Shared body of `image` and `video`: build, run, check, report."""
    try:
        engine = resolve(spec)
    except ValueError as exc:
        return err(str(exc))

    out = out or default_output(engine.modality, engine.output_suffix)
    # Absolute, because an engine with its own working directory would otherwise
    # write a relative path inside that directory, silently, where nobody looks.
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    try:
        argv = engine.argv(prompt, out, params)
    except ValueError as exc:
        return err(str(exc))

    def waiting(message: str) -> None:
        print(message, file=sys.stderr)

    try:
        # Issue #137. Held across the RUN only: resolving a spec and building
        # an argv cost nothing and should not make anyone queue.
        with exclusive.held(engine.modality, announce=waiting):
            r = proc.run(argv, timeout=engine.timeout, stream=engine.stream,
                         cwd=engine.cwd)
    except FileNotFoundError as exc:
        return err(f"{exc} is not installed or not on PATH.{INSTALL_HINT.get(spec.split(':')[0], '')}")
    except subprocess.TimeoutExpired:
        return err(f"{engine.name} timed out after {engine.timeout}s")
    except OSError as exc:
        return err(f"could not launch {engine.name}: {exc}")

    if not r.ok:
        return err(f"{engine.name} exited {r.returncode}\n{r.stderr.strip()}")

    if engine.modality == "image":
        expect = None
        if params.get("width") and params.get("height"):
            expect = (params["width"], params["height"])
        checked = image_check.check(out, expect=expect)
        if not checked.ok:
            return err(f"{engine.name} produced an unusable image: {checked.reason}")
        for w in checked.warnings:
            print(f"warning: {w}", file=sys.stderr)
    elif not out.exists() or out.stat().st_size == 0:
        return err(f"{engine.name} exited 0 but left no output at {out}")

    # The resolution is printed because a wall time and a peak mean nothing
    # without it: 512 costs 11.4 GiB here and 1024 costs 23.9.
    size = (f"{params['width']}x{params['height']}"
            if params.get("width") and params.get("height") else None)
    return say(path=out, seconds=r.seconds, peak_kb=r.peak_kb, size=size,
               human=f"{out}  ({r.seconds:.1f}s, "
                     f"peak {r.peak_kb / 1024 / 1024:.1f} GiB"
                     + (f", {size}" if size else "") + ")")


def cmd_image(a) -> int:
    params = {k: getattr(a, k) for k in ("width", "height", "steps", "seed")}
    return _generate(a.model, a.prompt, a.output, params)


def cmd_prompt(a) -> int:
    """Write a prompt for whatever this machine actually runs. Issue #138.

    The caller says what they want a picture of. What engine serves that, and
    how to command it, is this command's problem.
    """
    from harness import authoring, completion

    try:
        engine = authoring.resolved_for(a.lane)
        guide = authoring.for_lane(a.lane)
    except authoring.NoGuide as exc:
        return err(str(exc))
    if not a.about:
        # The guide alone is useful: it is the only place this knowledge is
        # readable by a person as well as by a model.
        note(f"\n{a.lane} runs {engine.name}\n")
        note(authoring.instructions(guide))
        emit(lane=a.lane, engine=engine.name, guide=guide["identity"],
             instructions=authoring.instructions(guide))
        return 0
    ask = (f"{authoring.instructions(guide)}\n\n"
           f"Write ONE prompt for this engine. The caller asked for:\n"
           f"{a.about}\n\n"
           f"Reply with the prompt and nothing else.")
    try:
        got = completion.complete(ask, model=a.model, gateway=a.gateway,
                                  modality="extract")
    except Exception as exc:  # noqa: BLE001
        return err(f"{exc}")
    note(got.strip())
    if not a.quiet:
        # The provenance goes to stderr so the prompt itself can be piped.
        print(f"[{engine.name}, guide {guide['identity']}, written by {a.model}]",
              file=sys.stderr)
    emit(prompt=got.strip(), lane=a.lane, engine=engine.name,
         guide=guide["identity"], model=a.model)
    return 0


def cmd_video(a) -> int:
    params = {k: getattr(a, k) for k in
              ("width", "height", "frames", "seconds", "steps", "seed")}
    return _generate(a.model, a.prompt, a.output, params)


def _text(a, modality: str, suffix: str, checker) -> int:
    try:
        raw = completion.complete(a.prompt, model=a.model, gateway=a.gateway,
                                  modality=modality)
    except completion.CompletionError as exc:
        return err(str(exc))

    body = completion.artifact(raw, modality)
    out = Path(a.output or default_output(modality, suffix))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")

    checked = checker(raw)
    for w in checked.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not checked.ok:
        # Written anyway: you cannot debug what was deleted.
        return err(f"wrote {out}, but it does not check out: {checked.reason}")
    return say(path=out, body=body, human=str(out))


#: The prompt an image model needs to produce something a tracer can use. A
#: photographic fox vectorizes into thousands of paths; flat shapes on white
#: vectorize into an icon.
TRACE_STYLE = ("flat vector illustration, simple clean shapes, bold outlines, "
               "solid colours, white background, no gradients, no texture")


def cmd_svg(a) -> int:
    method = getattr(a, "method", "llm")
    if method in ("trace", "icon"):
        return _svg_by_tracing(a, preset="illustration" if method == "trace"
                                          else "icon")
    return _text(a, "svg", ".svg", svg_check.check)


def _svg_by_tracing(a, preset: str = "illustration") -> int:
    """Draw it, then vectorize it.

    The measured answer for this lane. Five language models were compared on
    it and all five produce valid markup that is not the picture, because an
    LLM writes bezier coordinates it cannot see. Diffusion draws in pixel
    space, where "frog" is a shape it has seen.
    """
    out = Path(a.output or default_output("svg", ".svg")).resolve()
    png = out.with_suffix(".png")
    # The raster is KEPT. When the SVG is wrong the first question is always
    # whether the raster was wrong too, and deleting it throws away the only
    # way to answer.
    rc = _generate(a.engine, f"{a.prompt}, {TRACE_STYLE}", png,
                   {"width": a.width, "height": a.height,
                    "steps": None, "seed": a.seed})
    if rc != 0:
        return rc
    try:
        svg = vector.trace(png, preset=preset)
    except vector.VectorError as exc:
        return err(f"{png} was generated but could not be vectorized: {exc}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    checked = svg_check.check(svg)
    for w in checked.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not checked.ok:
        return err(f"wrote {out}, but it does not check out: {checked.reason}")
    return say(path=out, body=svg, human=str(out))


def cmd_web(a) -> int:
    return _text(a, "web", ".html", html_check.check)


def _answer(a, modality: str, context: str = "") -> int:
    """Ask for text and print it. The lanes that answer rather than draw.

    Stdout by default, because both of these produce something you pipe, read
    or paste. An SVG is an artifact you open in a viewer; a two-token answer to
    "how many tests failed" is not, and writing it to out/extract-<stamp>.txt
    would be a worse place to leave it than the terminal.
    """
    try:
        raw = completion.complete(a.prompt, model=a.model, gateway=a.gateway,
                                  modality=modality, context=context)
    except completion.CompletionError as exc:
        return err(str(exc))

    body = completion.artifact(raw, modality)

    # #143. `svg` and `web` are checked before the caller sees them and `code`
    # was not, which is backwards: it is the one lane whose output is meant to
    # be executed. Neither check here RUNS anything -- harness/checks/code.py
    # does that, and it needs a case's assertions, which a one-off prompt has
    # no equivalent of. These are warnings rather than a verdict because the
    # caller's target environment is not necessarily this machine.
    if modality == "code":
        broken = code_check.syntax_error(body)
        if broken:
            print(f"warning: does not parse, {broken}", file=sys.stderr)
        missing = code_check.unresolvable_imports(body)
        if missing:
            print(f"warning: imports not installed here: {', '.join(missing)}",
                  file=sys.stderr)

    if getattr(a, "output", None):
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        return say(path=out, body=body, human=str(out))
    return say(body=body, human=body)


def cmd_code(a) -> int:
    return _answer(a, "code")


def cmd_extract(a) -> int:
    if a.file:
        source = Path(a.file)
        if not source.exists():
            return err(f"no such file: {source}")
        context = source.read_text(encoding="utf-8")
    else:
        # A terminal with nobody piping into it reads as an empty string, which
        # is the case below rather than a hang.
        context = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not context.strip():
        return err("no material to read: pass --file, or pipe it in. "
                   "Answering a question about a log nobody supplied would "
                   "invent one.")
    return _answer(a, "extract", context=context)


def cmd_say(a) -> int:
    text = sys.stdin.read() if a.text == "-" else a.text
    if not text.strip():
        return err("nothing to say")
    out = Path(a.output or default_output("speech", ".wav"))
    try:
        # The voice name carries its model, reference clip and language code.
        # A cloned voice is three coupled settings, and getting one wrong fails
        # by naming another.
        audio.speak_as(a.voice, text, out=out, speed=a.speed,
                       base_url=a.base_url)
    except ValueError as exc:
        return err(str(exc))
    except audio.AudioError as exc:
        return err(str(exc))
    if a.play:
        # THE FILE IS ALREADY WRITTEN. A machine with no player is a missing
        # convenience, not a failed synthesis, so this warns and still reports
        # where the audio is.
        try:
            proc.run(audio.play_argv(out))
        except audio.AudioError as exc:
            print(f"warning: {exc}", file=sys.stderr)
    return say(path=out, human=str(out))


def cmd_discover(a) -> int:
    """What can this machine do, and what has never been measured?

    Built as a command rather than done by hand because the answer changes
    every time anything is installed or any eval is run. A number in a document
    is wrong by the next commit.
    """
    if getattr(a, "loop", False):
        return _report_loop(a)
    if getattr(a, "sweep", False):
        return _report_sweep(a)
    if getattr(a, "inspect", False):
        return _report_inspect(a)
    if getattr(a, "judge", False) and getattr(a, "from_store", False):
        return _report_judge_store(a)
    if getattr(a, "queue", False):
        return _report_queue(a)
    if getattr(a, "screen", False):
        return _report_screen(a)
    if getattr(a, "winners", False):
        return _report_winners(a)
    if getattr(a, "coverage", False):
        return _report_coverage(a)
    if getattr(a, "neighbors", False):
        return _report_neighbors(a)
    if getattr(a, "control", False):
        return _report_control(a)
    if getattr(a, "recurrence", False):
        return _report_recurrence(a)
    if getattr(a, "revisit", False):
        return _report_revisit(a)
    if getattr(a, "evidence", False):
        return _report_evidence(a)
    if getattr(a, "sources", False):
        return _report_sources(a)
    if getattr(a, "feeds", False):
        return _report_feeds(a)
    if a.external:
        if not a.lane:
            return err("--external needs a --lane: the registries are asked "
                       "different questions per modality")
        try:
            found = discovery.external(a.lane)
        except ValueError as exc:
            return err(str(exc))
        if a.json:
            print(json.dumps({"candidates": [vars(c) for c in found]}, indent=2))
            return 0
        if not found:
            print("nothing new found. Either this machine has measured what "
                  "the registry knows about, or there is no network.")
            return 0
        print(f"\n{a.lane}: candidates the registry has that nothing here has "
              f"measured")
        print("(proposals, not conclusions -- the eval decides)")
        for c in found:
            print(f"\n  {c.name}")
            print(f"    {c.source}")
            print(f"    {c.note}")
            print(f"    -> uv run python -m evals.run {c.how}")
        return 0

    caps = discovery.annotate(discovery.capabilities())
    if a.lane:
        caps = [c for c in caps if c.lane == a.lane]
    if a.gap:
        # A broken row is not a gap: running the command only refuses.
        caps = [c for c in caps
                if not c.measured and c.present and not c.blocked]

    if a.json:
        print(json.dumps({"capabilities": [vars(c) for c in caps]}, indent=2))
        return 0

    if not caps:
        print("nothing found" if not a.gap else "no gaps: everything here has been measured")
        return 0

    by_lane: dict[str, list] = {}
    for c in caps:
        by_lane.setdefault(c.lane, []).append(c)
    for lane in sorted(by_lane):
        print(f"\n{lane}")
        for c in sorted(by_lane[lane], key=lambda c: (c.measured, c.name)):
            # A recorded decision is not a defect, so it gets its own mark.
            if c.kind == "decision":
                mark = "declined"
            # BROKEN outranks measured: a thing can be measured and broken.
            elif c.blocked:
                mark = "BROKEN"
            elif not c.present:
                mark = "MISSING"
            elif c.measured:
                mark = "measured"
            else:
                mark = "NEVER RUN"
            print(f"  {mark:9} {c.kind:7} {c.name}")
            if c.blocked:
                print(f"            !! {c.blocked}")
            elif not c.present and c.note:
                print(f"            !! {c.note}")
            elif not c.measured:
                print(f"            -> {c.how}")
    # A declined tool is not an unmeasured gap, so it stays out of the ratio.
    countable = [c for c in caps if c.kind != "decision"]
    total, done = len(countable), sum(1 for c in countable if c.measured)
    print(f"\n{done}/{total} measured. The rest have never been run here.")
    _warn_stale_sources()
    return 0


def _warn_stale_sources() -> None:
    """Discovery nobody remembers to run is discovery that does not happen."""
    from harness import feeds

    try:
        stale = [r for r in feeds.staleness() if r["stale"]]
    except Exception:  # noqa: BLE001
        return
    if not stale:
        return
    names = ", ".join(r["name"] for r in stale[:4])
    print(f"\n{len(stale)} discovery source(s) not read in "
          f"{feeds.interval_days()} days: {names}")
    print("  soh discover --feeds     read them now")
    print("  soh discover --sources   when each was last read")


def _report_control(a) -> int:
    """A judge is a metric, and a metric without a control is noise.

    REPEATED, and that is the whole point of this command. The judge samples
    and nothing pins a seed, so one run gave gap +4 and the next +2 on
    identical inputs. control_repeated() was built for that, was tested, and
    nothing called it -- this command went to the single-shot form, so the
    sentence authorising every score in the project came from one draw.
    Issue #172.
    """
    from harness import judge
    runs = max(1, getattr(a, "runs", 3))
    try:
        got = judge.control_repeated(runs=runs, shape=getattr(a, "shape", "")
                                     or "described",
                                     gateway=getattr(a, "gateway", "") or "")
    except Exception as exc:  # noqa: BLE001
        return err(f"control failed: {exc}")
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    print(f"\nrubric {got['rubric']}, judge {got['model']}, "
          f"shape {got['shape']}, {got['runs']} run(s)")
    for r in got["rows"]:
        print(f"  {r['outcome']:5} {r['score']:2}  {r['name']:20} {r['why'][:52]}")
    gaps = ", ".join(f"{g:+d}" for g in got["gaps"])
    print(f"\n  gap per run {gaps}   spread {got['spread']}")
    if got["separates"]:
        print(f"  SEPARATES in all {got['runs']}. Scores from this rubric may "
              f"be used to rank.")
        return 0
    print(f"  DOES NOT SEPARATE: {got['separated_in']} of {got['runs']} runs. "
          f"No ranking may be drawn from this rubric.")
    return 1


def _report_revisit(a) -> int:
    """Verdicts another machine made whose condition THIS machine now meets.

    A refusal is routinely a fact about one box: `needs-cuda` is true where
    there is no cuda runtime and false where there is, and `too-big` is
    measured against a ceiling that describes one 32 GB machine. Until #266 the reason lived in prose, so
    a verdict made elsewhere was a dead end -- there was no way to ask which
    of them this machine could now answer.
    """
    from harness import memory_store as ms

    store = ms.connect()
    try:
        here = ms.this_machine()
        rows = ms.revisitable(store)
        if getattr(a, "requeue", False) and rows:
            ms.requeue_revisitable(store)
    finally:
        store.close()
    print(f"this machine: {here['fingerprint']}")
    print(f"  runtimes {here['runtimes'] or '-'}, "
          f"ceiling {here['ceiling_gb']:.0f} GiB, "
          f"memory {here['memory_gb']:.0f} GB\n")
    if not rows:
        print("nothing to revisit: no verdict from another machine has a "
              "condition this one satisfies.")
        return 0
    print(f"{len(rows)} candidate(s) refused for a reason that no longer "
          f"applies here:\n")
    for r in sorted(rows, key=lambda r: (r["lane"] or "", r["name"])):
        print(f"  {(r['lane'] or '-'):8} {r['name']}")
        where = r["decided_on"] or "an unrecorded machine"
        print(f"           {r['outcome']} on {where}: "
              f"{(r['detail'] or '')[:70]}")
        print(f"           waiting on {r['until']}, which this machine meets")
    if getattr(a, "requeue", False):
        print(f"\nre-queued {len(rows)} for the inspect tier.")
    else:
        print("\n--requeue sends them back to inspect: a verdict is never "
              "deleted.")
    return 0


def _report_evidence(a) -> int:
    """Verdicts whose receipt is no longer on disk.

    A verdict whose evidence is gone cannot be re-judged. Schema 10 exists
    because verdicts were recorded from runs that never reached a model, and
    undoing those required READING the runs back. That migration ran once and
    nothing has checked since.
    """
    from harness import memory_store as ms

    store = ms.connect()
    try:
        gone = ms.dangling_receipts(store)
        total = store.execute(
            "SELECT COUNT(*) c FROM verdicts WHERE run_path != ''"
        ).fetchone()["c"]
    finally:
        store.close()
    if not gone:
        print(f"every one of the {total} verdicts that names a run can still "
              f"reach it.")
        return 0
    print(f"{len(gone)} of {total} verdicts name a run that is no longer on "
          f"disk, so they cannot be re-judged:\n")
    for r in sorted(gone, key=lambda r: r["name"]):
        print(f"  {r['outcome']:9} {r['tier']:8} {r['name']}")
        print(f"            {r['run_path']}")
    print("\nThese are not deleted: a verdict is a record. They are reported "
          "so a re-judgement is known to be impossible rather than assumed "
          "to be available.")
    return 0


def _report_recurrence(a) -> int:
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        rows = ms.recurrence(conn, minimum=2)
        stats = ms.precision(conn)
        per_source = ms.by_source(conn)
        extract = ms.extraction(conn)
    finally:
        conn.close()
    if a.json:
        print(json.dumps({"recurrence": rows, "totals": stats,
                          "by_source": per_source,
                          "extraction": extract}, indent=2))
        return 0
    if not rows:
        print("nothing seen more than once yet. Run `soh discover --feeds`.")
    else:
        print("\nseen more than once (recurrence beats a single mention):")
        for r in rows:
            span = (r["last_seen"] - r["first_seen"]) / 86400.0
            print(f"  {r['times']}x over {span:5.1f}d  {r['name'][:44]:46}"
                  f" {r['sources']} source(s)")
    print(f"\n{stats['proposals']} proposals, {stats['resolved']} resolved, "
          f"{stats['verdict_measured']} measured, "
          f"{stats['verdict_declined']} declined")
    if per_source:
        print("\nper source (issue #49: precision is a query, not a count):")
        print(f"  {'source':24} {'proposed':>8} {'resolved':>8} {'settled':>8}")
        for r in per_source:
            print(f"  {r['source']:24} {r['proposals']:8d} "
                  f"{r['resolved']:8d} {r['settled']:8d}")
    if extract:
        print("\nextraction precision: of the names pulled out of prose, how "
              "many were real")
        print(f"  {'source':24} {'kept':>6} {'dropped':>8} {'precision':>10}")
        for r in extract:
            reasons = ", ".join(f"{k} {v}" for k, v in
                                sorted(r["reasons"].items(), key=lambda kv: -kv[1]))
            print(f"  {r['source']:24} {r['kept']:6d} {r['dropped']:8d} "
                  f"{r['precision']:10.2f}   {reasons}")
    return 0


def shard(names: list, spec: str) -> list:
    """The slice of the work this worker owns, as `i/n`.

    WITHOUT THIS A FAN-OUT IS FICTION. `parallelism: 4` on a Job whose pods all
    receive the same arguments is four workers doing identical work: four times
    the API budget, four times the clones, one result, and four writers racing
    on the same rows.

    A STRIDE, not a contiguous block. The candidate list arrives ranked, so
    splitting it into blocks would give worker 0 every strong candidate and the
    last worker the tail -- the slowest repos to clone are not evenly spread
    either, and blocks turn that into one straggler. `names[i::n]` interleaves,
    which is both simpler and better balanced.

    Empty spec means the whole list, so the CLI on a laptop is unchanged.
    """
    if not spec:
        return names
    try:
        i, n = (int(part) for part in spec.split("/", 1))
    except ValueError:
        raise SystemExit(f"--shard wants i/n, got {spec!r}")
    if n < 1 or not 0 <= i < n:
        raise SystemExit(f"--shard {spec} is not a slice of {n} workers")
    return names[i::n]


def resolve_registry(name: str, client, model=None) -> tuple[str, dict | None]:
    """Which registry answers for a name nothing wrote a registry down for.

    THE MIGRATION CANNOT ANSWER THIS. A name lifted from prose was resolved
    against HuggingFace by the sweep and the store kept the reddit permalink,
    so 223 of 235 rows carry no evidence either way (#167). Guessing from the
    shape of the string would be free and wrong: an `org/name` is a valid id in
    both namespaces, and a definite 404 is now terminal, so a wrong guess
    settles a real model as missing for good.

    HuggingFace first, on the same argument feeds.candidates() already makes in
    its two passes: where both answer, the model is the thing the eval can run.

    Returns the registry and whatever the answering registry already handed
    over, so the caller does not ask a second time: both of these rate-limit,
    and a repeated question is a request spent on nothing. Raises Gone only
    when BOTH say no; an empty registry means nothing could be told, which
    settles nothing.
    """
    from harness import github, inspect as ins
    from harness import memory_store as ms

    model = model or ins.hf_model
    reachable = False
    try:
        return ms.HUGGINGFACE, model(name)
    except ins.Gone:
        reachable = True
    except ins.InspectError:
        pass
    try:
        return ms.GITHUB, client.repo(name)
    except github.NotFound:
        if reachable:
            raise ins.Gone(f"{name}: neither registry has anything by that name")
    except github.GitHubError:
        pass
    return "", None


def _report_inspect(a) -> int:
    """Read a candidate's source before anyone downloads its weights. #61."""
    from harness import github, inspect as ins
    from harness import memory_store as ms

    client = github.Client(budget=getattr(a, "budget", 900))
    work = paths.home() / "cache" / "clones"
    work.mkdir(parents=True, exist_ok=True)
    store = ms.connect()
    try:
        if a.repos:
            # org/name is valid in both registries, so ask rather than assume:
            # a HuggingFace model named here was cloned from GitHub. #424.
            work_items = [(n, "") for n in a.repos]
        elif getattr(a, "from_store", False):
            # The rung the ladder was missing: what the sweep found, rather
            # than the crowd. Without this the two tiers read different
            # sources and nothing consumes a swept proposal.
            #
            # ASKED OF EACH REGISTRY SEPARATELY. One list handed to one API is
            # how 227 of 235 swept candidates 404ed: every name the sweep
            # writes is a HuggingFace id and this tier only knew how to clone
            # from GitHub. Issue #167.
            limit = getattr(a, "top", 10) * 5
            work_items = [(n, r) for r in ms.REGISTRIES
                          for n in ms.pending(store, limit=limit, registry=r,
                                              screened=False)]
            # And the ones the store cannot route, which it resolves rather
            # than guesses at. See resolve_registry().
            work_items += [(n, "") for n in
                           ms.pending(store, limit=limit, registry="",
                                      screened=False)]
            # CONSUME IN THE CONSUMER'S ORDER. `pending` sorts by corroboration
            # and recency; the fetch tier reads the same queue in rank order,
            # by the value of the information a screen would buy. Two tiers
            # ordering one queue by different keys means the producer sizes
            # rows the consumer will never reach, and both halves look healthy
            # -- RULE #275, and the reason a loop run sized 50 candidates and
            # still fetched nothing. Rows the fetch tier cannot see keep their
            # place at the back rather than being dropped.
            work_items = _in_fetch_order(store, work_items)
        else:
            work_items = [(n.repo, ms.GITHUB) for n in
                          __import__("harness.neighbors", fromlist=["x"])
                          .neighbors(client=client, top=getattr(a, "top", 10))]
        work_items = shard(work_items, getattr(a, "shard", ""))
        out = []
        for repo, registry in work_items:
            card = None
            if not registry:
                try:
                    registry, card = resolve_registry(repo, client)
                except ins.Gone as exc:
                    err(f"{repo}: {exc}")
                    try:
                        ms.decide(store, repo, "broken", tier=ms.INSPECT,
                                  detail=str(exc)[:200], reason=reasons.UPSTREAM)
                    except ms.IllegalTransition:
                        pass   # a later tier already answered it
                    continue
                if not registry:
                    err(f"{repo}: neither registry could be reached, so it "
                        f"stays unanswered")
                    continue
                ms.set_registry(store, repo, registry)
            if registry == ms.HUGGINGFACE:
                try:
                    fit = ins.inspect_model(repo, data=card)
                except ins.Gone as exc:
                    # A definite 404 is an answer about the candidate, so it is
                    # recorded as one. An unreachable registry is not.
                    err(f"{repo}: {exc}")
                    try:
                        ms.decide(store, repo, "broken", tier=ms.INSPECT,
                                  detail=str(exc)[:200], reason=reasons.UPSTREAM)
                    except KeyError:
                        pass   # named on the command line, never proposed
                    except ms.IllegalTransition:
                        pass   # a later tier already answered it
                    continue
                except ins.InspectError as exc:
                    err(f"{repo}: {exc}")
                    continue
            else:
                try:
                    meta = client.repo(repo) if card is None else card
                except github.GitHubError as exc:
                    err(f"{repo}: {exc}")
                    continue
                try:
                    fit = ins.inspect(repo, work, meta=meta)
                except ins.InspectError as exc:
                    err(f"{repo}: {exc}")
                    continue
            out.append(fit)
            ms.record(store, ms.Seen(
                name=repo, source="inspect", registry=registry,
                kind="weights" if registry == ms.HUGGINGFACE else "repo",
                url=(f"https://huggingface.co/{repo}"
                     if registry == ms.HUGGINGFACE
                     else f"https://github.com/{repo}"),
                resolved=repo, lane=fit.lanes.get(repo, ""), why=fit.why,
                lane_source=fit.card.lane_source,
                # WHAT IT IS, beside what the verdict said about it. The judge
                # reads this; with only a name it cannot rank at all (#175).
                description=fit.description))
            ms.set_size(store, repo, fit.largest)
            if ms.set_lane(store, repo, fit.lanes.get(repo, ""),
                           source=fit.card.lane_source):
                print(f"    lane corrected from the card: {repo} "
                      f"-> {fit.lanes[repo]}")
            # The card's facts as columns and lineage rows; readers ask
            # these, never the description. #414.
            ms.set_card(store, repo, fit.card)
            # A thing that cannot run here is ANSWERED, so it is terminal and
            # never proposed again. "unknown" settles nothing, deliberately.
            outcome = {"fits": "queued", "unknown": ""}.get(fit.verdict, "declined")
            if outcome:
                # The tier that read the repo writes why and what would end
                # the wait; nothing re-reads its sentence. #270, #333, #408.
                try:
                    ms.decide(store, repo, outcome, tier=ms.INSPECT,
                              size_bytes=fit.largest if fit.verdict == "fits" else 0,
                              upstream_idle_days=fit.upstream_idle_days,
                              reason=ins.reason_of(fit), until=ins.until_of(fit),
                              detail=f"{fit.verdict}: {fit.why}"[:200])
                except ms.IllegalTransition as exc:
                    print(f"    kept its state: {exc}")
            # The WEIGHTS are what a download queue can act on. The repo is
            # something to install and screen, and the two are not the same
            # queue: queueing the repo sent GitHub names to snapshot_download,
            # which wants a HuggingFace id, and every one of them 401'd.
            if fit.verdict != "fits":
                continue
            if registry == ms.HUGGINGFACE:
                # A model IS the weight, so there is no second queue to fill
                # and nothing to retire: what `queued` means here is already
                # recorded above.
                continue
            # In HEADLINE order, not smallest-first: the smallest named
            # weight is almost always a tokenizer or a helper, and the first
            # queue built that way filled with them. Issue #68.
            ranked = [m for m in fit.headline if m in fit.weights][:3]
            # Re-inspecting CORRECTS the queue rather than only extending it:
            # weights this repo queued under an older ranking, and no longer
            # ranks, are retired. Issue #73.
            ms.retire_unlisted(
                store, repo, keep=ranked, why=(
                    "no longer among this repo's top-ranked weights"))
            for model_id in ranked:
                size = fit.weights[model_id]
                if size > ins.ceiling_bytes():
                    continue
                ms.record(store, ms.Seen(
                    name=model_id, source="inspect", kind="weights",
                    registry=ms.HUGGINGFACE,
                    url=f"https://huggingface.co/{model_id}",
                    resolved=model_id, lane=fit.lanes.get(model_id, ""),
                    why=f"named by {repo}"))
                ms.set_size(store, model_id, size)
                # THE CARD OVERWRITES A GUESS. record() keeps the first
                # non-empty lane; this one was read off the publisher's own
                # task, so it outranks whatever the sweep inferred. #227.
                if ms.set_lane(store, model_id, fit.lanes.get(model_id, "")):
                    print(f"    lane corrected from the card: {model_id} "
                          f"-> {fit.lanes[model_id]}")
                ms.link(store, repo, model_id, "needs")
                # A sighting never reopens a decided name; decide() refuses. #399.
                try:
                    ms.decide(store, model_id, "queued", tier=ms.INSPECT,
                              size_bytes=size, reason=reasons.CANDIDATE,
                              detail=f"lane={fit.lanes.get(model_id) or '-'} "
                                     f"named by {repo}")
                except ms.IllegalTransition:
                    continue
    finally:
        store.close()
    if getattr(a, "judge", False):
        _judge_fits(out, store_path=None)
    if a.json:
        print(json.dumps({"inspected": [vars(f) for f in out]}, indent=2))
        return 0
    print("\nread from source, with nothing downloaded and nothing run")
    for f in out:
        print(f"\n  {f.verdict.upper():14} {f.repo}")
        print(f"    {f.why}")
        bits = []
        if f.mlx:
            bits.append("MLX-native")
        if f.mps and not f.mlx:
            bits.append("torch/MPS")
        if f.cuda_mentioned:
            bits.append(f"mentions {', '.join(f.cuda_mentioned[:2])}")
        if f.unsized:
            bits.append(f"{len(f.unsized)} weight(s) unsized")
        if bits:
            print(f"    {'; '.join(bits)}")
    return 0


def cmd_verify(a) -> int:
    """Establish that each lane works, by running its own default. #234."""
    import subprocess

    from harness import report, verify

    state = report.state()
    tasks = verify.plan(state["lanes"], only=getattr(a, "lane", ""),
                        force=getattr(a, "all", False))
    if not tasks:
        # NOT "every lane has a receipt". A parked lane has none and is
        # excluded from the plan by design, so saying so here would report a
        # decision as a measurement -- the exact confusion #244 removed from
        # the report a few lines away.
        parked = [l for l in state["lanes"] if l.get("parked")]
        note("every lane that should run here has a recent receipt")
        for l in parked:
            note(f"  {l['lane']} is parked and was not run: {l['parked']}")
        emit(planned=[], parked={l["lane"]: l["parked"] for l in parked})
        return 0

    runnable = [t for t in tasks if not t.skip]
    budget = sum(t.cost_s for t in runnable)
    note(f"\n{len(runnable)} lane(s) to verify, roughly {budget // 60}m "
         f"{budget % 60}s in total:\n")
    for t in tasks:
        note(f"  {t.lane:8} {t.candidate[:40]:40} "
             f"{t.skip or f'~{t.cost_s}s'}")
        note(f"           {t.why}")
    if not getattr(a, "run", False):
        note("\n--run to spend it. Nothing is downloaded either way.")
        emit(planned=[_task_row(t) for t in tasks], ran=False)
        return 0

    rc = 0
    results = []
    for t in runnable:
        # Its own directory, read back from the store by that name. #410.
        out = paths.new_run(t.lane)
        argv = t.argv + ["--out", str(out)]
        note(f"\n=== {t.lane} ===\n    {' '.join(argv)}", flush=True)
        proc = subprocess.run(argv, capture_output=True, text=True)
        data = _receipt_at(out) or {}
        got = verify.verdict(data) if proc.returncode == 0 else "broken"
        line = (verify.summarise(t.lane, data) if proc.returncode == 0
                else (proc.stderr.strip().splitlines() or ["no stderr"])[-1])
        results.append((t.lane, got, line))
        note(f"    {got.upper()}: {line[:150]}")
        if got == "broken":
            rc = 1
    note("\n=== what the lanes do ===")
    for lane, got, _ in results:
        note(f"  {got:8} {lane}")
    emit(ok=rc == 0, planned=[_task_row(t) for t in tasks], ran=True,
         results=[{"lane": l, "verdict": g, "summary": s_}
                  for l, g, s_ in results])
    return rc


def _task_row(t) -> dict:
    return {"lane": t.lane, "candidate": t.candidate, "cost_s": t.cost_s,
            "skip": t.skip, "why": t.why}


def _evalset(name: str) -> Path:
    p = Path(name).expanduser()
    return p if p.is_dir() else paths.home() / "evalsets" / name


def cmd_throughput(a) -> int:
    """How much faster an alias goes with several requests in flight. #310."""
    import json as _json
    from harness import throughput
    try:
        rows = [_json.loads(l) for l in open(a.texts, encoding="utf-8") if l.strip()]
    except (OSError, ValueError) as exc:
        return err(f"cannot read {a.texts}: {exc}")
    texts = [str(r.get(a.field) or "") for r in rows][: a.n]
    levels = tuple(int(x) for x in a.levels.split(",") if x.strip())
    note(f"{a.model}: {len(texts)} texts at {levels} in flight, "
         f"max_tokens {a.max_tokens}", flush=True)
    got = throughput.sweep(a.model, texts, levels=levels,
                           max_tokens=a.max_tokens, gateway=a.gateway)
    if got and "warmup_s" in got[0]:
        note(f"  warm-up {got[0]['warmup_s']:.2f}s, not counted"
             f"{'' if got[0]['warmup_ok'] else ' (FAILED)'}", flush=True)
    base = got[0]["per_hour"] or 1
    for r in got:
        note(f"  {r['concurrency']:2d} in flight  {r['per_hour']:7.1f}/h  "
             f"x{r['per_hour'] / base:.2f}  p50 {r['p50_s']:6.2f}s  "
             f"p95 {r['p95_s']:6.2f}s  errors {r['errors']}  "
             f"tokens {r['completion_tokens']}", flush=True)
    emit(model=a.model, max_tokens=a.max_tokens, levels=got)
    return 0


def cmd_jobs(a) -> int:
    """The work queue every caller shares. #353."""
    from harness import workqueue as wq

    global _JSON
    rest, title = list(a.rest), a.title
    # REMAINDER swallows options written after the action.
    priority = a.priority
    while rest[:1] in (["--title"], ["--json"], ["--priority"]):
        if rest[0] == "--json":
            _JSON, rest = True, rest[1:]
        elif len(rest) > 1 and rest[0] == "--title":
            title, rest = rest[1], rest[2:]
        elif len(rest) > 1:
            try:
                priority = int(rest[1])
            except ValueError:
                return err(f"--priority takes a number, not {rest[1]!r}")
            rest = rest[2:]
        else:
            break
    if rest[:1] == ["--"]:
        rest = rest[1:]
    elif a.action != "add" and "--json" in rest:
        # Only `add` carries a command of its own; elsewhere a flag is a flag.
        _JSON, rest = True, [x for x in rest if x != "--json"]
    a.title = title
    try:
        if a.action == "add":
            job = wq.add(rest, title=a.title, priority=priority, requested_by="cli")
            note(f"queued {job['id']}: {job['title']}")
            emit(job=job)
            return 0
        if a.action == "priority":
            if len(rest) != 2:
                return err("priority needs a job id and a number: soh jobs priority 0005 10")
            try:
                job = wq.set_priority(rest[0], int(rest[1]))
            except ValueError as exc:
                return err(str(exc))
            note(f"{job['id']} priority {job['priority']}: {job['title']}")
            emit(job=job)
            return 0
        if a.action == "cancel":
            if not rest:
                return err("cancel needs a job id")
            job = wq.cancel(rest[0])
            note(f"cancelled {job['id']}: {job['title']}")
            emit(job=job)
            return 0
    except ValueError as exc:
        return err(str(exc))
    if a.action in ("pause", "resume"):
        (wq.pause if a.action == "pause" else wq.resume)()
        ok, why = wq.gate()
        note(f"{a.action}d; next job {'may start' if ok else 'waits'}: {why}")
        emit(paused=wq.paused(), gate_open=ok, why=why)
        return 0
    got = wq.jobs()
    ok, why = wq.gate()
    note(f"{'a job is running' if wq.running() else 'nothing running'}; "
         f"{sum(j['state'] == wq.PENDING for j in got)} pending; next job "
         f"{'may start' if ok else 'waits'}: {why}")
    shown = ([j for j in got if j["state"] == wq.RUNNING] + wq.order(
        [j for j in got if j["state"] == wq.PENDING])
             + [j for j in got if j["state"] in (wq.DONE, wq.FAILED)])
    for j in shown:
        rc = "" if j["rc"] is None else f" rc={j['rc']}"
        pri = int(j.get("priority") or 0)
        note(f"  {j['id']}  {j['state']:8}{rc:7}  p{pri:<3} {j['title']}")
    emit(running=wq.running(), gate_open=ok, why=why, jobs=got)
    return 0


def cmd_memory(a) -> int:
    """How far this machine's memory goes before macOS pushes back. #299."""
    from harness import memory_store as ms, ramp

    if a.action == "show":
        store = ms.connect()
        try:
            limits = {r["fingerprint"]: ramp.runs(store, r["id"]) for r in
                      store.execute("SELECT DISTINCT m.id, m.fingerprint "
                                    "FROM memory_limits l JOIN machines m "
                                    "ON m.id = l.machine_id").fetchall()}
        finally:
            store.close()
        if not limits:
            return err("nothing measured yet: soh memory ramp records one")
        note(json.dumps(limits, indent=1, sort_keys=True))
        emit(limits=limits)
        return 0
    note(f"allocating {a.step_gb:g} GB at a time until macOS first warns; "
         f"everything is freed at the end", flush=True)
    from harness import exclusive
    try:
        with exclusive.held("ramp", announce=lambda m: note(m, flush=True)):
            got = ramp.run(step_gb=a.step_gb, settle_s=a.settle,
                           floor_pct=a.floor_pct, cap_gb=a.cap_gb)
    except ValueError as exc:
        return err(str(exc))
    if not got["steps"]:
        return err(f"nothing was allocated ({got['stopped']}), so there is "
                   f"nothing to record")
    for s in got["steps"]:
        note(f"  {s['gb']:5.1f} GB  level {s['level']}  free {s['free_pct']}%  "
             f"available {s['available_gb']:.1f} GB  wired {s['wired_gb']}  "
             f"swapouts {s['swapouts']}", flush=True)
    note(f"\nstopped: {got['stopped']}; last step at normal pressure: "
         f"{got['last_normal_gb']:g} GB on top of what was already running")
    if got["margin_gb"] is not None:
        note(f"margin: macOS warned {got['margin_gb']:.1f} GB short of the "
             f"guard's own available figure; the guard now reserves "
             f"the largest margin measured on this machine")
    store = ms.connect()
    try:
        mid = ms.remember_machine(store)
        ramp.save(store, got, mid)
    finally:
        store.close()
    note(f"recorded for machine {mid} in the store")
    emit(machine_id=mid, report=got)
    return 0


def cmd_disk(a) -> int:
    """What the weights cache holds and what may go. #370, #373."""
    import time as _time

    from harness import disk, memory_store as ms
    now = _time.time()
    try:
        conn = ms.connect()
    except Exception as exc:  # noqa: BLE001
        note(f"no discovery store ({exc}); deletion disabled")
        conn = None
    try:
        if getattr(a, "record", False):
            if conn is None:
                return err("no discovery store; nothing to record into")
            from harness import downloads
            got = downloads.record_unrecorded(conn)
            note(f"recorded {got['recorded']} path(s) with no row, stamped "
                 f"{got['gone']} gone row(s) removed")
        inv = disk.inventory(conn)
        if not a.delete:
            note(disk.table(inv, now))
            emit(**disk.as_json(inv, now))
            return 0
        doomed = disk.plan(inv, now, a.delete)
        size = sum(e.size for e in doomed)
        for e in doomed:
            note(f"  {disk.gib(e.size):>7} GiB  {e.name}  ({e.why})")
        if not inv.complete:
            return err("refusing to delete: " + "; ".join(inv.problems))
        if not doomed:
            note(f"nothing in {a.delete} is safe to delete")
            emit(removed=[], bytes=0)
            return 0
        if not a.yes:
            if _JSON:
                return err(f"--json needs --yes to delete {len(doomed)} "
                           f"entries ({disk.gib(size)} GiB)")
            try:
                answer = input(f"delete {len(doomed)} entries, "
                               f"{disk.gib(size)} GiB? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                note("nothing deleted")
                return 1
        removed = disk.delete(inv, now, a.delete, conn)
    finally:
        if conn is not None:
            conn.close()
    ok = [r for r in removed if "error" not in r]
    freed = sum(r["bytes"] for r in ok)
    for r in removed:
        if "error" in r:
            note(f"  not removed: {r['path']}: {r['error']}")
    note(f"removed {len(ok)}, freed {disk.gib(freed)} GiB")
    emit(ok=len(ok) == len(removed), removed=removed, bytes=freed)
    return 0 if len(ok) == len(removed) else 1


def cmd_rubric(a) -> int:
    """Label an eval set by hand, then score local models against it. #286."""
    from harness import label_server, rubric_eval as rv

    root = _evalset(a.set)
    try:
        s = rv.load_set(root)
    except (OSError, ValueError, KeyError) as exc:
        return err(f"no usable eval set at {root}: {exc}")
    if a.action == "label":
        label_server.serve(root, port=a.port, repeat_rate=a.repeat_rate,
                           open_browser=not a.no_browser)
        return 0
    if a.action == "status":
        agree, total = rv.self_agreement(root)
        note(f"{s.rubric.stamp}: {len(rv.labels(root))} of {len(s.items)} "
             f"labelled, {len(rv.gold(root))} decided, "
             f"self-agreement {agree}/{total} on repeats")
        emit(rubric=s.rubric.stamp, items=len(s.items),
             labelled=len(rv.labels(root)), decided=len(rv.gold(root)),
             self_agreement=[agree, total])
        return 0
    candidates = [c.strip() for c in (a.candidates or "").split(",") if c.strip()]
    if not candidates:
        return err("--candidates is required for run")
    try:
        from harness import exclusive
        with exclusive.held("eval", announce=lambda m: note(m, flush=True)):
            report = rv.run(s, candidates, a.gateway)
    except ValueError as exc:
        return err(str(exc))
    out = paths.runs() / f"rubric-{time.strftime('%Y%m%d-%H%M%S')}-{s.rubric.name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(report, indent=2),
                                      encoding="utf-8")
    agree, total = report["ceiling"]
    note(f"{report['rubric']}  floor {report['floor']:.2f} (always the most "
         f"common label)  ceiling {agree}/{total} (your repeats)")
    for model, row in report["candidates"].items():
        note(f"  {model:24} agree {row['agree']}/{row['n']} "
             f"({row['agreement']:.2f})  valid {row['valid']}/{row['n']}  "
             f"median {row['median_s']}s"
             f"{'' if row['beats_floor'] else '  NOT above the floor'}")
    note(f"receipt: {out / 'results.json'}")
    emit(path=out / "results.json", report=report)
    return 0


def _run_name(run: Path) -> str:
    """A run under the runs dir by its directory name, anything else by path."""
    try:
        return str(run.resolve().relative_to((paths.home() / "runs").resolve()))
    except ValueError:
        return str(run)


def cmd_judge(a) -> int:
    """Serve the page a person votes on, for a lane no program can score.

    Some capabilities have no metric -- not because the right one has not been
    found, but because the field has none. There is no per-clip
    style-similarity measure; Frechet Audio Distance is distributional and
    cannot score one clip; human preference studies are the ground truth for
    music generation. This project hit that wall three times and answered by
    not building the capability. Issue #273.
    """
    from harness import adopt, candidates, human, judge_server, lanes, winners
    from harness import memory_store as ms

    run = Path(a.run).expanduser()
    if not run.is_absolute():
        run = paths.home() / "runs" / run
    receipt = _receipt_at(run)
    if not receipt:
        return err(f"no stored run for {run}")
    lane = (a.lane or receipt.get("receipt", {}).get("modality") or "").strip()
    if not lane:
        return err("that receipt does not name its modality; pass --lane")
    if not lanes.human_judged(lane):
        note(f"note: the {lane} lane has programmatic checks and is not in "
             f"lanes.HUMAN_JUDGED, so this verdict is extra rather than the "
             f"deciding one.")
    pairs = human.pairings(receipt, run)
    if not pairs:
        return err("no two candidates in that run share a case, so there is "
                   "nothing to compare")
    specs = receipt.get("specs") or {}

    def _record(lane_, pairs_):
        """Write the lane's verdict the moment it becomes decidable."""
        won, why = human.lane_verdict(lane_, pairs_)
        if won is None:
            return
        incumbent = adopt.default_for(lane_, winners.typed().get(lane_, ""))
        names = sorted({p["a"] for p in pairs_} | {p["b"] for p in pairs_})
        store = ms.connect()
        try:
            candidates.from_receipt(store, specs, lane=lane_)
            for challenger in names:
                spec = (candidates.get(store, challenger) or {}).get("spec")
                if not spec:
                    note(f"  not recorded: no stored candidate maps "
                         f"{challenger} to a spec a lane can run")
                    continue
                if incumbent not in (challenger, spec):
                    # Decided on the names the pairs carry, recorded as the
                    # spec, which is what a lane can run. #337.
                    try:
                        adopt.record(store, dataclasses.replace(
                            adopt.decide_by_hand(lane_, incumbent, challenger,
                                                 pairs_), challenger=spec))
                    except ms.IllegalTransition as exc:
                        note(f"  skipped {exc}")
            store.commit()
        finally:
            store.close()
        note(f"  recorded: {won or 'no preference'} -- {why}")

    # A RUN THAT IS ALREADY JUDGED RECORDS WITHOUT ANYONE CLICKING. Recording
    # only on a new answer leaves a finished run unrecorded forever, and
    # recording only at shutdown loses it whenever the server is killed rather
    # than interrupted -- which is how a service manager stops things.
    _record(lane, pairs)

    try:
        judge_server.serve(lane, receipt, port=a.port,
                           open_browser=not a.no_browser, on_answer=_record,
                           run=_run_name(run), run_dir=run)
    except OSError as exc:
        return err(f"could not serve on port {a.port}: {exc}")
    settled = [p for p in pairs
               if human.decided(lane, p["case"], p["a"], p["b"]) is not None]
    note(f"\n{len(settled)} of {len(pairs)} pairing(s) settled")
    for p in pairs:
        got = human.decided(lane, p["case"], p["a"], p["b"])
        if got is None:
            continue
        note(f"  {p['case']:14} {got or 'no preference'}")

    # THE VERDICT GOES IN THE STORE, or the whole exercise is a page somebody
    # clicked. adopt.record already knows how to write a winner that has no
    # proposal row (#262), so a candidate named on a command line lands the
    # same way one from a sweep does.
    won, why = human.lane_verdict(lane, pairs)
    if won is None:
        note(f"\nnot recorded: {why}")
        emit(lane=lane, settled=len(settled), pairings=len(pairs),
             recorded=False, why=why)
        return 0
    note(f"\n{lane}: {'no preference' if not won else won}")
    note(f"  {why}")
    _record(lane, pairs)           # idempotent; covers a run that was already
    emit(lane=lane, settled=len(settled), pairings=len(pairs),  # fully judged
         recorded=True, winner=won or None, why=why)            # before serving
    return 0


def cmd_report(a) -> int:
    """Write the status page. Issue #231."""
    from harness import report

    if getattr(a, "json", False):
        print(json.dumps(report.state(), indent=1, default=str))
        return 0
    if getattr(a, "auto_publish", ""):
        from harness import publish
        on = a.auto_publish == "on"
        print(f"{publish.set_enabled(on)}: publishing after each discovery "
              f"loop is {'on' if on else 'off'}")
        return 0
    if getattr(a, "export", False) or getattr(a, "publish", False):
        return _report_export(a)
    out = report.write(getattr(a, "out", "") or None)
    state = report._load_state(out.with_suffix(".json"))
    lanes = state.get("lanes") or []
    unverified = [l["lane"] for l in lanes if l.get("unverified")]
    stale = [l["lane"] for l in lanes if l.get("stale")]
    print(f"\n{out}")
    if unverified:
        print(f"  {len(unverified)} lane(s) with no receipt on this machine: "
              f"{', '.join(unverified)}")
    # A PARKED LANE IS NOT A GAP. Reported separately so the two reasons for
    # having no receipt do not read as one. #244.
    for l in lanes:
        if l.get("parked"):
            print(f"  {l['lane']} is parked: {l['parked']}; "
                  f"revisit when {l['parked_until']}")
    if stale:
        print(f"  {len(stale)} lane(s) not measured in "
              f"{report.STALE_LANE_DAYS:.0f} days: {', '.join(stale)}")
    return 0


def _report_export(a) -> int:
    """This machine's report as public JSON, written locally or published. #432."""
    from harness import publish
    try:
        if a.publish:
            print(f"wrote {publish.publish_here()} on the {publish.BRANCH} branch")
        else:
            print(publish.write_export(getattr(a, "out", "") or None))
    except publish.ExportRefused as exc:
        print(exc, file=sys.stderr)
        return 1
    except publish.GhError as exc:
        print(f"publish failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_fetch(a) -> int:
    """Download what the inspect tier queued. Issue #62."""
    from harness import fetching, inspect as ins
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows = fetching.queued(store, lane=want)
        if not rows:
            note(f"nothing queued in the {want} lane. "
                 f"`soh discover --inspect` fills the queue." if want else
                 "nothing queued. `soh discover --inspect` fills the queue.")
            emit(queued=[], orphans=[])
            return 0
        if not a.run:
            testable = [r for r in rows if r.get("lane")]
            orphans = [r for r in rows if not r.get("lane")]
            note(f"\n{len(testable)} queued, "
                 f"{fetching.free_bytes() / fetching.GIB:.0f} GiB free. "
                 f"--run to start, one at a time. The score is the judged "
                 f"score of the repo that named the weight.")
            for r in testable[:20]:
                size = int(r.get("size_bytes") or 0)
                gib = f"{size / fetching.GIB:5.1f} GiB" if size else "  no size"
                note(f"  {r['score'] or 0:>4.0f}  {gib}  {r['lane']:6s} "
                     f"{r['resolved'] or r['name']}")
            if orphans:
                note(f"\n{len(orphans)} named but NOT queued: nothing here can "
                     f"measure them. Not a verdict on the model -- the eval "
                     f"suite has no case, runner or metric for this kind of "
                     f"thing, and building one is sometimes the work.")
                for r in orphans[:10]:
                    note(f"        {r['resolved'] or r['name']}")
            emit(free_bytes=fetching.free_bytes(),
                 queued=[{"repo": r["resolved"] or r["name"], "lane": r["lane"],
                          "score": r["score"], "size": int(r.get("size_bytes") or 0)}
                         for r in testable],
                 orphans=[r["resolved"] or r["name"] for r in orphans])
            return 0
        gib = getattr(a, "budget_gib", None)
        budget = int(float(gib) * fetching.GIB) if gib else None
        fetched = []
        for got in fetching.run(store, limit=a.limit, lane=want,
                                budget=budget):
            fetched.append(got)
            note(f"  {'OK  ' if got['ok'] else 'skip'} {got['repo']}: {got['why']}")
    finally:
        store.close()
    emit(fetched=fetched)
    return 0


def _judge_fits(fits, store_path=None) -> int:
    """Score inspected candidates with the facts the clone produced. #69.

    Ordering matters: INSPECT runs before JUDGE now. Cheapest-first was never
    the real justification for the old order -- inspect costs seconds and the
    judge costs about a second -- and the judge scoring a generic description
    3/10 while the inspect tier had already proved the thing MLX-native was the
    tier with more evidence losing to the tier with less.
    """
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))
    store = ms.connect(store_path)
    try:
        print("\n  judged, with the source read first:")
        for f in fits:
            weights = (f"{f.smallest / (1024**3):.1f} to "
                       f"{f.largest / (1024**3):.1f} GiB" if f.largest else "")
            item = judge.describe(
                f.repo, why=f.description, source="github-crowd",
                inspected=f"{f.verdict}: {f.why}",
                platform=("MLX-native" if f.mlx else
                          "torch/MPS" if f.mps else ""),
                weights=weights)
            try:
                score, why = judge.score(item, rubric)
            except Exception as exc:  # noqa: BLE001
                err(f"{f.repo}: {exc}")
                continue
            print(f"    {score:2d}/10  {f.repo:36.36s} {why[:56]}")
            try:
                ms.decide(store, f.repo, "queued", tier=ms.JUDGE, score=score,
                          reason=reasons.CANDIDATE,
                          rubric=rubric.stamp, judge=rubric.model,
                          detail=why[:200])
            except (KeyError, ms.IllegalTransition):
                pass
    finally:
        store.close()
    return 0


def _report_queue(a) -> int:
    """What a screen would teach us, best first. Issue #175.

    NOT A PREDICTION OF WHO WINS. The judge tier tried that and could not: two
    controls shaped like this data both failed to separate six models with known
    opposite outcomes, because the fact that separated them was produced by
    RUNNING them and a registry card has never held it.

    Arithmetic over what the store already knows, so it is deterministic and
    needs no gateway -- which is worth as much as the ordering, given the
    instrument it stands in for had to be run three times to be believed.
    """
    from harness import rank
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows, waiting = _queueable(store, want)
        retests = ms.retest_counts(store)
    finally:
        store.close()
    if not a.json:
        print(retest_line(retests))
    if not rows:
        print(f"nothing queued in the {want} lane that a screen has not answered"
              if want else "nothing queued that a screen has not answered")
        return 0
    # RANK THEM ALL, THEN TAKE THE TOP. rank() drops what no screen can answer
    # -- a laneless row, an adapter -- so the denominator has to come from
    # after that or it counts rows that will never be offered. The image lane
    # held 11 waiting of which 6 were LoRAs. Issue #209.
    ranked = rank.rank(rows, serving=rank.serving(),
                       measured_lanes=rank.lanes_with_receipts())
    waiting, ranked = len(ranked), ranked[:getattr(a, "top", 25)]
    if a.json:
        print(json.dumps({"queue": ranked, "waiting": waiting,
                          "retests": retests}, indent=2))
        return 0
    print(f"\n{len(ranked)} of {waiting} waiting, by what a screen would teach:")
    for r in ranked:
        print(f"\n  {r['value']:+6.1f}  {r['name']}")
        print(f"          {r['value_why'] or 'nothing known about it'}")
    return 0


def retest_line(c: dict) -> str:
    """The queue report's retest summary. #431."""
    return (f"retests: {c['due']} due, {c['pending']} scheduled, "
            f"{c['final']} final after 3; {c['recovered']} recovered false "
            f"negative(s)")


def _report_coverage(a) -> int:
    """What discovery never saw. Issue #99.

    Extraction precision measures the quality of what is CAUGHT. This measures
    reach: of the things this project actually adopted, which did a configured
    source ever surface. A source list is not a measurement of coverage.
    """
    from harness import coverage
    from harness import memory_store as ms

    store = ms.connect()
    try:
        got = coverage.report(store)
    finally:
        store.close()
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    print(f"\n{got['adopted']} things this machine runs or measured:")
    print(f"  {len(got['found']):3d} surfaced by a discovery source first")
    print(f"  {len(got['late']):3d} surfaced only after they were already run")
    print(f"  {len(got['holes']):3d} never surfaced by any source")
    if got["by_source"]:
        print("\n  credited with a find:")
        for source, n in got["by_source"].items():
            print(f"    {source:24} {n}")
    if got["proposed"]:
        # A source producing plenty that nobody has run is a different problem
        # from one producing nothing, and they want opposite fixes.
        print("\n  proposals produced (adopted or not):")
        for source, n in got["proposed"].items():
            print(f"    {source:24} {n}")
    holes = [h for h in got["holes"] if "why" not in h]
    ours = [h for h in got["holes"] if "why" in h]
    if ours:
        print(f"\n  {len(ours)} in the store only because one of our own tiers "
              f"put it there:")
        for h in ours[:12]:
            print(f"    {h['name']}")
    if holes:
        print(f"\n  {len(holes)} no configured source ever produced:")
        for h in holes[:20]:
            print(f"    {h['name']:44} {'/'.join(h['how'])}")
    if got["unlinked"]:
        print(f"\n  {len(got['unlinked'])} receipt key(s) on "
              f"{sum(got['unlinked'].values())} result rows name no candidate "
              f"and are not counted")
    return 0


def _report_winners(a) -> int:
    """What the receipts say won each lane, against what this file has typed in.

    The four DEFAULT_*_MODEL constants above are a hand copy of a measurement
    that lives in the stored runs. Both are worth having -- a default that
    moved because somebody ran an eval last night is a CLI two machines
    disagree about -- but a hand copy with nothing watching it is this
    project's most-bitten failure class.
    """
    from harness import adopt, winners

    from harness import memory_store as ms
    store = ms.connect()
    try:
        best = winners.beaten_in(store)
        rows = winners.disagreements(store)
        serves = adopt.lane_defaults(store)
    finally:
        store.close()
    if a.json:
        print(json.dumps({"typed": winners.typed(), "serves": serves,
                          "measured": best, "disagreements": rows}, indent=2))
        return 0
    #: exact agreement needs no mark; the other two each say which they are.
    MARK = {"exact": " ", "": "*"}
    print(f"\n  {'lane':9} {'serves':34} {'measured here':30} run")
    for lane, name in sorted(serves.items()):
        got = best.get(lane)
        if not got:
            print(f"  {lane:9} {name:34} {'-- not in any receipt':30}")
        else:
            mark = MARK.get(got["match"], "*")
            print(f" {mark}{lane:9} {name:34} "
                  f"{got['candidate'] + ' ' + str(got['pass_rate']):30} "
                  f"{got['run']}")
    print("\n  * beaten in a run it was in")
    beaten = [r for r in rows if r["state"] == "beaten"]
    unmeasured = [r for r in rows if r["state"] == "unmeasured"]
    if beaten:
        print(f"\n  {len(beaten)} default(s) lost a comparison they were in:")
        for r in beaten:
            print(f"    {r['modality']}: {r['measured']} beat {r['typed']} "
                  f"in {r['run']}")
    if unmeasured:
        # NOT a disagreement. A default that appears in no receipt was never in
        # the room, and reporting silence as conflict is how an inventory
        # becomes noise nobody reads.
        print(f"\n  {len(unmeasured)} default(s) appear in no receipt here, so "
              f"nothing on this machine can check them:")
        for r in unmeasured:
            print(f"    {r['modality']}: {r['typed']}")
    return 0


def _screen_plan(want: str) -> list[dict]:
    from harness import rank, screen
    from harness import memory_store as ms
    store = ms.connect()
    try:
        # THE SAME DEFECT AS _report_queue, at the tier that actually runs the
        # model. `--top 2` sampled 8 rows of 114 and filtered those, so the
        # loop fetched two image models and then said "nothing queued to
        # screen". Issue #209.
        rows, _ = _queueable(store, want)
    finally:
        store.close()
    ranked = rank.rank(rows, serving=rank.serving(),
                       measured_lanes=rank.lanes_with_receipts())
    return screen.plan(ranked)


def screenable_backlog(want: str = "", plan=None, room=None) -> list[str]:
    """On disk, runnable, and fitting in memory now: what a fetch would queue behind. #396."""
    from harness import screen
    plan = _screen_plan(want) if plan is None else plan
    room = room or (lambda r: memory.check_model(r["name"], spec=r["candidate"])[0])
    return [r["name"] for r in plan if r["state"] == screen.READY and room(r)]


def _report_screen(a) -> int:
    """Run the cheapest real thing, and record whether it ran at all. #53.

    SAYS WHAT IT WOULD DO AND STOPS, unless told otherwise. `--run` is the same
    convention `lh fetch` uses, and for the same reason: this is the first tier
    that spends real time and real memory, and one that starts doing so because
    something ranked well is how a laptop ends up unusable overnight.
    """
    import subprocess

    from harness import candidates, rank, router, screen
    from harness import memory_store as ms

    want = (getattr(a, "lane", "") or "").strip().lower()
    full = _screen_plan(want)
    if not full:
        print("nothing queued to screen")
        return 0
    # Ready rows come from the whole plan: the rank head is often rows the
    # fetch skipped for budget, which crowded out what it fetched. #376.
    ready = [r for r in full if r["state"] == screen.READY]
    planned = full[:getattr(a, "top", 5)]
    planned += [r for r in ready if r not in planned]
    if not getattr(a, "run", False):
        print(f"\n{len(planned)} candidate(s), {len(ready)} ready to screen:")
        for r in planned:
            print(f"\n  {r['state']:16} {r['name']}")
            print(f"    {r['why_not']}")
            if r["state"] == screen.READY:
                print(f"    {' '.join(screen.argv(r))}")
        print("\n  --run to screen the ready ones; nothing is downloaded either "
              "way")
        return 0
    if not ready:
        return err("nothing is ready to screen: fetch weights first, and note "
                   "that a screen never downloads")

    store = ms.connect()
    try:
        for r in ready[:getattr(a, "limit", 1)]:
            print(f"\n── {r['name']}", flush=True)
            # Headroom, including what is already resident. #284.
            room, why_not = memory.check_model(r["name"], spec=r["candidate"])
            if not room:
                print(f"   QUEUED: {why_not}")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: {why_not}"[:600],
                                  reason=reasons.MEMORY,
                                  until=f"memory_gb:>{memory.available_gb():.1f}")
                continue
            # Its own receipt directory, not the newest for the modality. #282.
            outdir = paths.runs() / f"screen-{int(time.time())}-{r['modality']}"
            try:
                proc = subprocess.run(screen.argv(r, outdir=outdir),
                                      capture_output=True, text=True)
            except OSError as exc:
                print(f"   QUEUED: the screen could not start: {exc}")
                ms.decide_or_skip(store, r["name"], "queued", tier=ms.SCREEN,
                                  detail=f"not screened: the screen could not start: "
                                         f"{exc}"[:600], reason=reasons.HARNESS)
                continue
            # The RUN's own summary, read from what it wrote rather than parsed
            # out of its chatter: a tier that infers an outcome from stdout is
            # a tier that reports success when the format changes.
            stored = _receipt_at(outdir)
            summary = stored.get("summary") if stored else None
            ran = (stored or {}).get("specs") or {}
            candidates.from_receipt(store, ran, lane=r["modality"],
                                    proposals={s: r["name"] for s in ran.values()})
            cid = candidates.ensure(store, r["candidate"], proposal=r["name"],
                                    lane=r["modality"])
            key = candidates.key_for(store, r["candidate"])
            # Read once, here, and only when the run wrote no receipt. #408.
            stderr_class = "" if summary is not None else reasons.classify(
                (proc.stderr or "")[-2000:], reasons.STDERR, r["candidate"])
            verdict = screen.outcome(proc.returncode, summary,
                                     candidate=r["candidate"], key=key,
                                     stderr_class=stderr_class,
                                     facts=ms.this_machine())
            got, why = verdict.outcome, verdict.detail
            print(f"   {got.upper()}: {why}")
            if proc.returncode != 0:
                err(proc.stderr.strip()[-400:] or "no stderr")
            # The stderr tail stays as evidence for a person; the reason and
            # the class are the columns code reads. #281, #408.
            evidence = " ".join((proc.stderr or "").split())[-300:]
            detail = f"{why} || {evidence}" if evidence else why
            ms.decide_or_skip(store, r["name"], got, tier=ms.SCREEN,
                              detail=detail[:600],
                              run_id=(stored or {}).get("run_id"),
                              reason=verdict.reason, until=verdict.until,
                              candidate_id=cid)
            router.release_spec(r["candidate"], f"screened {r['name']}")
            if verdict.failure_class in reasons.STOPS:
                print(f"   {verdict.failure_class}: the model server or GPU is "
                      f"suspect; stopping the screen so the rest are not "
                      f"spent on it (#404)")
                return 1
    finally:
        store.close()
    return 0


def _report_judge_store(a) -> int:
    """Score what the inspect tier queued and no judge has read. #148 phase 3.

    THE RUNG ABOVE --inspect --from-store. _judge_fits() can only see the Fit
    objects produced in its own process, so a judge has never been able to
    reach the store: after #167 that left real candidates with real verdicts
    and nothing ranking them.

    THE CONTROL RUNS FIRST AND THE TIER REFUSES WITHOUT IT. A judge is a
    metric, this one samples, and a tier that scores unattended on a schedule
    has nobody present to doubt it. `--no-control` exists for a person watching
    the output, never for a Job.
    """
    from harness import judge
    from harness import memory_store as ms

    gateway = getattr(a, "gateway", "") or ""
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))

    # THE WORK FIRST, THEN THE GATE, and in that order for two reasons. The
    # control costs a model call per control item, so a Job whose queue is
    # empty would otherwise pay eighteen of them to prove a rubric separates
    # and then score nothing. And a store that cannot be reached should be
    # found in the first second rather than after the judging budget is spent:
    # the first run of this tier in a cluster did exactly that, spending its
    # control on a gateway and then dying on a Postgres in recovery.
    store = ms.connect()
    scored = 0
    try:
        rows = ms.judgeable(store, limit=getattr(a, "top", 25))
        rows = shard(rows, getattr(a, "shard", ""))
        waiting = ms.judgeable_total(store)
        if not rows:
            print("nothing queued by inspect that a judge has not already read")
            return 0

        if not getattr(a, "no_control", False):
            runs = max(1, getattr(a, "runs", 3))
            # THE SHAPE OF ITS OWN INPUT. This tier feeds the judge store
            # rows, so a control made of hand-written project descriptions
            # answers a question about different data -- it separated at +7
            # while every real candidate came back 3/10 (#175).
            shape = getattr(a, "shape", "") or "carded"
            try:
                got = judge.control_repeated(runs=runs, gateway=gateway,
                                             shape=shape)
            except Exception as exc:  # noqa: BLE001
                return err(f"control failed, so nothing was scored: {exc}")
            gaps = ", ".join(f"{g:+d}" for g in got["gaps"])
            print(f"control: rubric {got['rubric']}, judge {got['model']}, "
                  f"shape {got['shape']}, gap per run {gaps}, "
                  f"spread {got['spread']}")
            if not got["separates"]:
                return err(
                    f"the rubric separates in only {got['separated_in']} of "
                    f"{got['runs']} control runs, so nothing was scored. A "
                    f"score from a rubric that does not discriminate is a "
                    f"number, not a ranking")

        print(f"\njudging {len(rows)} candidate(s) the sweep found and the "
              f"source tier answered:")
        for row in rows:
            item = judge.describe(
                # The card first: a sighting's `why` is what one source said
                # on one day, and for a prose-swept id it is usually empty.
                row["name"], why=row.get("description") or row.get("why") or "",
                source=row.get("source") or "", times_seen=row.get("times") or 0,
                relevance=row.get("relevance") or 0,
                inspected=row.get("inspected") or "")
            try:
                score, why = judge.score(item, rubric, gateway=gateway)
            except Exception as exc:  # noqa: BLE001 - one bad reply is not a run
                err(f"{row['name']}: {exc}")
                continue
            print(f"  {score:2d}/10  {row['name']:40.40s} {why[:48]}")
            try:
                ms.decide(store, row["name"], "queued", tier=ms.JUDGE,
                          score=score, rubric=rubric.stamp, judge=rubric.model,
                          detail=why[:200], reason=reasons.CANDIDATE)
            except ms.IllegalTransition:
                continue   # answered by a later tier while this one scored
            scored += 1
    finally:
        store.close()
    left = max(0, waiting - scored)
    print(f"\n{scored} scored, under rubric {rubric.identity} judged by "
          f"{rubric.model}"
          + (f"; {left} still waiting" if left else ""))
    return 0


def _report_neighbors(a) -> int:
    """What the people who build what we run are looking at. Issue #58."""
    from harness import feeds, github, memory_store as ms, neighbors as nb

    client = github.Client(budget=getattr(a, "budget", 900))
    try:
        people = nb.cohort(client=client, limit=getattr(a, "crowd", 250))
    except github.GitHubError as exc:
        feeds.record_failure("github-crowd", str(exc))
        return err(f"{exc}. `gh auth status` to check the token.")
    if getattr(a, "control", False):
        got = nb.control(list(nb.DEFAULT_SEEDS), people, client)
        if a.json:
            print(json.dumps(got, indent=2))
            return 0
        print(f"\ncrowd of {got['crowd']}, ranking {len(got['top'])}")
        print(f"  expected and found : {', '.join(got['expected_found']) or 'NONE'}")
        print(f"  expected but absent: {', '.join(got['missing']) or 'none'}")
        print(f"  decoys in the top  : {', '.join(got['decoys_in_top']) or 'none'}")
        print(f"\n  SEPARATES: {got['separates']}")
        if not got["separates"]:
            print("  Do not quote a score from this run.")
        print("\n  by shared count alone, which is what we do NOT ship:")
        for r in got["raw_top"][:5]:
            print(f"    {r}")
        return 0

    found = nb.neighbors(people, client, top=getattr(a, "top", 25),
                         exclude=nb.DEFAULT_SEEDS)
    if a.json:
        print(json.dumps({"crowd": len(people),
                          "neighbors": [vars(n) for n in found]}, indent=2))
        return 0
    print(f"\nrepos concentrated in the crowd that builds what this machine "
          f"runs\n({len(people)} people, {client.spent} requests; a popularity "
          f"signal, not a measurement)")
    if client.stale:
        print(f"  {len(client.stale)} answer(s) served from a stale cache")
    for n in found:
        flag = "  ARCHIVED" if n.archived else ""
        print(f"\n  {n.score:.5f}  {n.repo}{flag}")
        print(f"    {n.shared} of {n.crowd} starred it; {n.stars} stars, "
              f"pushed {n.pushed}")
        if n.description:
            print(f"    {n.description[:100]}")
    # Into the store, so a sighting counts towards recurrence and the graph
    # finally has edges to walk. Seeds are recorded too, because link() needs
    # both ends to exist.
    store = ms.connect()
    try:
        feeds.record_fetch("github-crowd", store=store)
        for seed in nb.DEFAULT_SEEDS:
            ms.record(store, ms.Seen(name=seed, source="installed", kind="repo",
                                     registry=ms.GITHUB,
                                     url=f"https://github.com/{seed}",
                                     resolved=seed))
        for n in found:
            ms.record(store, ms.Seen(name=n.repo, source="github-crowd",
                                     registry=ms.GITHUB,
                                     url=f"https://github.com/{n.repo}",
                                     why=n.description, kind="repo",
                                     relevance=feeds.relevance(
                                         f"{n.repo} {n.description} "
                                         f"{' '.join(n.topics)}"),
                                     resolved=n.repo))
            for seed in nb.DEFAULT_SEEDS:
                ms.link(store, seed, n.repo, "crowd",
                        shared=n.shared, crowd=n.crowd, score=n.score)
        if getattr(a, "judge", False):
            _judge_neighbors(found, store)
    finally:
        store.close()
    return 0


def _judge_neighbors(found, store):
    """Score crowd proposals with the rubric. Same cheapest tier as the feeds.

    A repo card says more than a recap blurb, so the judge is shown the
    description, topics and how much of the crowd starred it.
    """
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        return err(str(exc))
    print("\n  judged:")
    for n in found:
        why = f"{n.description} [{n.language}; {', '.join(n.topics[:6])}]"
        row = store.execute(
            "SELECT v.detail FROM verdicts v JOIN proposals p "
            "ON p.id = v.proposal_id WHERE p.name = ? AND v.tier = 'inspect' "
            "ORDER BY v.id DESC LIMIT 1", (n.repo,)).fetchone()
        try:
            score, reason = judge.score(
                judge.describe(n.repo, why=why, source="github-crowd",
                               times_seen=n.shared,
                               inspected=(row["detail"] if row else "")),
                rubric)
        except Exception as exc:  # noqa: BLE001
            err(f"{n.repo}: {exc}")
            continue
        print(f"    {score:2d}/10  {n.repo:38.38s} {reason[:60]}")
        try:
            ms.decide(store, n.repo, "queued", tier=ms.JUDGE, score=score,
                      reason=reasons.CANDIDATE,
                      rubric=rubric.stamp, judge=rubric.model,
                      detail=reason[:200])
        except (KeyError, ms.IllegalTransition):
            pass
    return 0


def _report_sources(a) -> int:
    from harness import feeds

    rows = feeds.staleness()
    proposed = discovery.feed_sources()
    reachable = discovery.lane_reach()
    if a.json:
        print(json.dumps({"sources": rows, "reach": reachable,
                          "proposed": [vars(c) for c in proposed]}, indent=2))
        return 0
    print(f"\ndiscovery sources (interval {feeds.interval_days()} days, "
          f"${feeds.INTERVAL_ENV} to change)")
    for r in rows:
        age = ("never read" if r["age_days"] is None
               else f"{r['age_days']:.1f} days ago")
        mark = "STALE" if r["stale"] else "ok   "
        fails = (f"; {r['failures']} failed read(s) since: {r['last_error'][:80]}"
                 if r.get("failures") else "")
        print(f"  {mark} {r['name']:24} {age}{fails}")
        print(f"        {r['url']}")
    # WHICH LANES CAN BE REACHED AT ALL. Three lanes had no source and nobody
    # could see it, because nothing anywhere asked the question (#240). Read
    # through lanes.serves(), so the four text-served lanes correctly inherit
    # the text sources rather than reading as unreachable.
    print("\nlanes discovery can reach:")
    for lane, how in reachable.items():
        parts = list(how["feeds"])
        if how["registry"]:
            parts.append(f"{how['registry']} registry queries")
        print(f"  {'none ' if not parts else 'ok   '} {lane:8} "
              f"{', '.join(parts) or 'NO SOURCE: this lane can never fill its queue'}")

    if proposed:
        print("\nsources these feeds point at that we do not read:")
        for c in proposed:
            # Probing is the difference between a shortlist and a guess: half
            # of these hosts serve no feed at all. Issue #50. #182 fixed the
            # argument (the URL is in `source`, not `how`); this resolves the
            # host to its feed, which an example article link never is. #183.
            feed, why = feeds.find_feed(c.source)
            mark = "FEED " if feed else "none "
            print(f"  {mark} {c.name:20} {c.note}")
            print(f"        {feed or c.source}")
            print(f"        {why}")
        print(f"\n  Add one to {feeds.config_path()} to start reading it. "
              f"Deliberately manual: a source URL out of untrusted prose "
              f"should need a human nod.")
    return 0


#: Every source family, in the order a sweep reads them. Each entry is the
#: attribute cmd_discover dispatches on, so adding a source family here is the
#: only edit needed to put it in the sweep.
SOURCE_TIERS = ("feeds", "neighbors")


#: The loop, in order: (label, the attribute cmd_discover dispatches on, does
#: it need --run). Sweeping reads feeds and the GitHub API and takes about a
#: minute, which is the "find what exists" step and runs either way. INSPECT
#: CLONES SOURCE, measured at over ten minutes across a full queue, so it is
#: gated with the rest: a dry run that takes ten minutes is not a dry run.
def _queueable(store, want: str = "") -> tuple[list[dict], int]:
    """The waiting candidates in scope, and how many there are.

    SCOPE FIRST, THEN LIMIT. cmd_queue used to fetch `top * 4` rows and filter
    those, so `--lane` did not scope the queue: it sampled the backlog in
    whatever order the store returned it and kept whatever matched. At the
    default --top 25 the sample is 100 of 114 and the defect is invisible; at
    --top 2 it is 8, and the image lane reported empty while holding five
    candidates. A narrow budget is exactly when the scope matters most, and it
    was where the sampling bit hardest. Issue #209.

    The returned count is the in-scope total, because a scoped queue printing
    "5 of 114 waiting" answers a different question with its denominator than
    with its numerator.
    """
    from harness import rank
    from harness import memory_store as ms

    rows = ms.judgeable(store, limit=1_000_000)
    if want:
        rows = [r for r in rows if lanes.serves(rank.lane_of(r), want)]
    return rows, len(rows)


LOOP_STEPS = (("sweep", "sweep", False),
              ("inspect", "inspect", True),
              ("queue", "queue", False))

#: How many queued candidates the loop's inspect step sizes, which is NOT
#: `--top`. Those are two different questions and tying them together is what
#: made the loop inert: `--top` is how many candidates to carry the whole way
#: and spend disk on, so `--top 1` is a sensible thing to ask for, while
#: inspecting one row of a 46-row queue leaves the other 45 unsized and the
#: fetch tier refuses every one of them. Inspection downloads nothing.
LOOP_INSPECT = 50


def _in_fetch_order(store, work_items):
    """Reorder inspect's work to match the order the fetch tier will read.

    Returns the same items, never fewer: a name the fetch queue does not carry
    is still worth inspecting, it simply goes last.
    """
    from harness import fetching
    try:
        ranked = fetching.in_rank_order(
            fetching.queued(store, needs_lane=False), store)
    except Exception:  # noqa: BLE001
        # An ordering is an optimisation. Failing to compute one must not
        # stop the tier that does the actual work.
        return work_items
    place = {r["name"]: i for i, r in enumerate(ranked)}
    return sorted(work_items, key=lambda it: place.get(it[0], len(place)))


def _report_loop(a) -> int:
    """Every step from a sweep to an adopted winner. Issue #201.

    SAYS WHAT IT WOULD DO AND STOPS unless --run. Fetching weights and running
    a lane are the two operations that spend gigabytes and minutes, and a loop
    that starts doing either because something ranked well is how a laptop ends
    up unusable overnight.
    """
    import argparse as _ap

    from harness import adopt, rank
    from harness import memory_store as ms

    run = bool(getattr(a, "run", False))
    rc = 0
    for label, attr, needs_run in LOOP_STEPS:
        if needs_run and not run:
            print(f"\n=== {label} (skipped; --run) ===")
            continue
        print(f"\n=== {label} ===")
        flags = {f: f == attr for _, f, _ in LOOP_STEPS}
        extra = {}
        if attr == "inspect":
            # INSPECT WHAT THE SWEEP FOUND, not the crowd. cmd_inspect's own
            # comment calls --from-store "the rung the ladder was missing",
            # and the loop never passed it, so the loop inspected new GitHub
            # sightings while the QUEUE stayed unsized. Every one of 46 queued
            # candidates was then skipped by fetch with "no measured size;
            # inspect it first", immediately after the loop's own inspect step
            # had run. Two tiers in one command, reading different sources.
            extra = {"from_store": True, "top": LOOP_INSPECT}
        sub = _ap.Namespace(**{**vars(a), **flags, **extra, "loop": False})
        rc = cmd_discover(sub) or rc

    want = (getattr(a, "lane", "") or "").strip().lower()
    store = ms.connect()
    try:
        rows, _ = _queueable(store, want)
        if want:
            print(f"\n(scoped to the {want} lane: {len(rows)} candidate(s))")
        short = rank.wanted(rows)
        if short:
            print(f"\n=== lanes wanted ===")
            print(f"{len(short)} candidate(s) recur and no lane can test them. "
                  f"A lane is a decision for a person, so they are reported "
                  f"rather than ranked or invented:")
            for row in short[:10]:
                print(f"  {row.get('times', 0)}x  {row['name']}")
        stuck = rank.runnerless(rows)
        if stuck:
            print(f"\n=== runners wanted ===")
            print(f"{len(stuck)} candidate(s) have a lane and no runner that "
                  f"can load them. An engine entry is a decision for a person "
                  f"-- a guessed one is a binary that refuses the model "
                  f"several seconds into loading:")
            for row in stuck[:10]:
                print(f"  {row.get('lane', ''):8} {row['name']}\n"
                      f"           {row['why_not']}")
        print(f"\n=== adopted ===")
        current = adopt.current(store)
        if current:
            for lane, row in sorted(current.items()):
                print(f"  {lane:8} {row['spec']}  ({row['how']})")
        else:
            print("  nothing adopted yet; every lane serves its typed constant")
    finally:
        store.close()

    if not run:
        print("\ninspect, fetch, screen and measure not run. Add --run to "
              "spend the disk and the minutes.")
        return rc
    return _spend_and_settle(a, rc)


def _spend_and_settle(a, rc: int) -> int:
    """_loop_spend, then leave only lane defaults resident in the router. #444."""
    from harness import router
    try:
        rc = _loop_spend(a, rc)
    finally:
        router.settle("the discovery loop is done")
    _publish_if_enabled()
    return rc


def _publish_if_enabled() -> str:
    """Publish this machine's report when its publish switch is on. #432."""
    from harness import publish
    if not publish.enabled():
        return ""
    print("\n=== publish ===")
    try:
        path = publish.publish_here()
    except Exception as exc:  # noqa: BLE001
        print(f"  not published: {exc}")
        return ""
    print(f"  wrote {path} on the {publish.BRANCH} branch")
    return path


def _loop_spend(a, rc: int) -> int:
    """Fetch, screen, measure and adopt, ONE CANDIDATE AT A TIME.

    Serial by construction, not by accident. An eval sweeping aliases took this
    machine down by loading a 16 GiB model while a 7.8 GiB one was still
    resident (RULE #193). The budget is a ceiling on what this invocation will
    download, and `--top` a ceiling on how many candidates it will carry the
    whole way.
    """
    import argparse as _ap

    from harness import adopt, fetching, screen
    from harness import memory_store as ms

    from harness import disk

    print("\n=== retests ===")
    _reopen_retests()

    # After the retests, so a reopened candidate's weights are queued, not swept.
    print("\n=== disk ===")
    disk.sweep()

    top = int(getattr(a, "top", 3) or 3)
    budget = float(getattr(a, "budget_gib", 20.0) or 20.0)

    want = (getattr(a, "lane", "") or "").strip().lower()
    if want:
        print(f"\n(spending only on the {want} lane)")
    print(f"\n=== fetch (up to {top}, budget {budget:g} GiB) ===")
    backlog = screenable_backlog(want)
    if len(backlog) >= top:
        print(f"  skipped: {len(backlog)} candidate(s) already on disk wait "
              f"for a screen, and this run screens {top}")
    else:
        sub = _ap.Namespace(**{**vars(a), "loop": False, "run": True,
                               "limit": top, "json": False})
        rc = cmd_fetch(sub) or rc

    print(f"\n=== screen ===")
    sub = _ap.Namespace(**{**vars(a), "loop": False, "screen": True,
                           "run": True, "limit": top, "json": False})
    rc = cmd_discover(sub) or rc

    print(f"\n=== measure and adopt ===")
    store = ms.connect()
    try:
        fresh = measurable(store, top, want)
    finally:
        store.close()
    if not fresh:
        print("  nothing survived the screen, so there is nothing to measure. "
              "A screen that rejects everything is the tier doing its job.")
        return rc
    for row in fresh:
        rc = _measure_and_adopt(a, row) or rc
    return rc


def _reopen_retests(now: float | None = None) -> list[str]:
    """Reopen screen and measure rejections whose retest is due. #431."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        names = ms.reopen_due_retests(store, now)
    finally:
        store.close()
    print(f"  reopened {len(names)} rejection(s) for a retest")
    for n in names:
        print(f"    {n}")
    return names


def measurable(store, top: int, want: str = "") -> list[dict]:
    """Survivors in the scoped lane, filtered before the limit. #386."""
    from harness import memory_store as ms
    rows = ms.survivors(store, limit=1_000_000)
    if want:
        rows = [r for r in rows if lanes.serves(r.get("lane"), want)]
    return rows[:top]


def _measure_and_adopt(a, row: dict) -> int:
    """_measure, then unload the challenger it loaded. #444."""
    from harness import router
    loaded: list[str] = []
    try:
        return _measure(a, row, loaded)
    finally:
        for spec in loaded:
            router.release_spec(spec, f"measured {row['name']}")


def _measure(a, row: dict, loaded: list) -> int:
    """One challenger against the lane's incumbent, then the verdict.

    PAIRED AND IN ONE RUN. Both candidates see the same cases, the same repeat
    count and the same machine, so the only axis that moved is the candidate.
    Two separate runs would be two receipts that comparable() would refuse, and
    rightly.
    """
    import subprocess

    from harness import adopt, candidates, screen, winners
    from harness import memory_store as ms

    name = row["name"]
    # A text candidate is filed under `code` and can be measured in web, svg
    # and extract too. When the caller scoped the loop to one of those, that
    # is the lane to measure in: the incumbent, the cases and the metric all
    # belong to the lane being asked about, not the one the row was filed
    # under. #207.
    want = (getattr(a, "lane", "") or "").strip().lower()
    lane = (want if want and lanes.serves(row.get("lane"), want)
            else lanes.canonical(row.get("lane")))
    store = ms.connect()
    try:
        spec = candidates.for_proposal(store, lane, name,
                                       row.get("attaches_to") or "")
    finally:
        store.close()
    if not spec:
        return err(f"{name}: screened in the {lane} lane and no candidate "
                   f"spec can be built for it")
    incumbent = adopt.default_for(lane, winners.typed().get(lane, ""))
    if not incumbent:
        print(f"  {name}: the {lane} lane has no incumbent to beat, so there "
              f"is nothing to compare against. Measure it on its own first.")
        return 0
    inc_spec = screen.candidate_for(lane, incumbent) or incumbent
    if spec == inc_spec:
        # An adopted winner is the incumbent; measuring it against itself
        # wrote `declined` for the lane's own default. #393.
        print(f"  {name}: already the {lane} lane's default ({spec})")
        _settle(name, "measured", f"{lane}: already the lane's default")
        return 0
    # THE PAIR MUST REACH THE SAME SERVER. One --gateway serves the whole run,
    # so when the challenger's repo id sends it to mlx_lm.server the incumbent
    # cannot travel as a LiteLLM alias: :8081 has never heard of `q3-4b`, the
    # control scored 0 of 27, and the run had nothing to compare against. The
    # config maps every alias to the upstream behind it. #223.
    if screen.routed_gateway(name):
        upstream = screen.upstream_of(incumbent)
        if upstream:
            inc_spec = screen.candidate_for(lane, upstream) or upstream
    # NAME THE DIRECTORY, DO NOT GUESS AT IT AFTERWARDS. A newest-receipt read
    # whichever directory sorted highest, and `legacy-ev-small-code` outranks
    # every timestamp because `l` sorts above `2`. The loop measured two
    # candidates and then read a receipt from a different experiment. #222.
    out = (paths.home() / "runs"
           / f"{time.strftime('%Y%m%d-%H%M%S')}-adopt-{lane}")
    argv = ["uv", "run", "python", "-m", "evals.run", "--modality", lane,
            "--repeat", str(int(getattr(a, "repeat", 3) or 3)),
            "--out", str(out),
            "--candidates", f"{inc_spec},{spec}"]
    # ROUTE IT THE WAY THE SCREEN DOES. LiteLLM validates `model` against its
    # alias table and a discovered candidate is always a repo id, so the
    # measure sent every request to a server that was never going to accept
    # the name: 0/27 at 11ms a case, reported as "does not beat the incumbent
    # on the lane's metric". #223, which is #206 at the tier its fix did not
    # reach.
    route = screen.routed_gateway(name)
    if route:
        argv += ["--gateway", route]
    print(f"\n  {lane}: {name} against {incumbent}")
    print(f"    {' '.join(argv)}", flush=True)
    loaded.append(spec)
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        err(proc.stderr.strip()[-400:] or "no stderr")
        return 1
    data = _receipt_at(out)
    if not data:
        return err(f"{name}: the run stored no receipt for {out}, so nothing "
                   f"can be adopted from it")
    summary = data.get("summary") or {}
    rows = data.get("rows") or []
    # The run's own specs map is the mapping; store it, then read keys back.
    store = ms.connect()
    try:
        candidates.from_receipt(store, data.get("specs") or {}, lane=lane,
                                proposals={spec: name})
        inc_key = candidates.key_for(store, inc_spec)
        ch_key = candidates.key_for(store, spec)
    finally:
        store.close()
    inc_row = _summary_row(summary, inc_key)
    ch_row = _summary_row(summary, ch_key)
    # ASSERT THE RUN IS THE ONE THAT WAS ASKED FOR. Naming the directory stops
    # the loop reading a stranger's receipt; this stops it reading a receipt
    # that is its own and yet describes a different exam, which a crashed or
    # partially-skipped candidate produces. #222.
    if len(summary) and not (inc_row or ch_row):
        return err(f"{name}: the receipt at {out} names {sorted(summary)!r} "
                   f"and neither candidate this run asked for, so it does not "
                   f"describe the run that was just made")
    if not inc_row:
        # THE INCUMBENT IS THE CONTROL. A candidate measured beside a control
        # that did not run says nothing about the candidate, which is the
        # lesson the tts lane already paid for (#194/#195). Name it as the
        # control rather than as a missing summary key: a 15-minute run that
        # ends in "the summary names [...]" makes the reader go looking in the
        # receipt for a spelling problem. Issue #214.
        return err(f"{name}: the incumbent {incumbent} contributed no rows, so "
                   f"this run has no control and nothing can be concluded from "
                   f"it. The summary names {sorted(summary)!r}")
    if not ch_row:
        return err(f"{name}: the challenger contributed no rows. The summary "
                   f"names {sorted(summary)!r}")
    # A CANDIDATE THAT NEVER RAN IS NOT A CANDIDATE THAT LOST. Every row a
    # harness refusal means the request never reached a model, and handing
    # that to adopt.decide dresses a routing failure as a quality result.
    # The rows carry the runner's failure class. #223, #408.
    # THE CONTROL MUST HAVE RUN. This is the general form of the refusal check
    # below, and it catches every variant of "the request never reached a
    # model" without anyone having to classify it first: a 404 from a
    # doubled /v1 got past the phrase list, both candidates scored 0/27, and
    # the loop reported "does not beat the incumbent on the lane's metric".
    # A candidate measured beside a control that passed nothing says nothing
    # about the candidate. #223, and the lesson the tts lane paid for in #194.
    if not int(inc_row.get("passed") or 0):
        return err(f"{name}: the incumbent {incumbent} passed "
                   f"0 of {inc_row.get('total') or '?'}, so this run has no "
                   f"working control and nothing can be concluded from it. "
                   f"Fix the lane before reading the challenger.")
    refused = _all_refused(rows, ch_row.get("candidate") or name)
    if refused:
        store = ms.connect()
        try:
            ms.decide(store, name, "queued", tier=ms.SCREEN,
                      detail=f"not measured: {refused}",
                      run_id=data.get("run_id"), reason=reasons.HARNESS)
        except (KeyError, ms.IllegalTransition):
            pass      # measured by hand, never proposed; the report still stands
        finally:
            store.close()
        return err(f"{name}: every case was refused before it reached a model "
                   f"({refused}). The incumbent passed, so this says nothing "
                   f"about the candidate and it stays queued.")
    verdict = adopt.decide(lane, inc_row, ch_row, rows)
    print(f"    {'ADOPTED' if verdict.adopt else 'kept the incumbent'}: "
          f"{verdict.why}")
    store = ms.connect()
    try:
        # On the proposal the candidate maps to, so it leaves survivors. #393.
        adopt.record(store, verdict, spec=spec, run_id=data.get("run_id"))
    except ms.IllegalTransition as exc:
        print(f"  skipped {exc}", flush=True)
    finally:
        store.close()
    return 0


def _settle(name: str, outcome: str, detail: str) -> None:
    from harness import memory_store as ms
    store = ms.connect()
    try:
        ms.decide(store, name, outcome, tier=ms.MEASURE, detail=detail[:200],
                  reason=reasons.CANDIDATE)
    except (KeyError, ms.IllegalTransition):
        pass
    finally:
        store.close()


def _summary_row(summary: dict, key: str) -> dict | None:
    """The summary entry under the receipt key the candidates table holds. #407."""
    if not key or key not in summary:
        return None
    return {**(summary[key] or {}), "candidate": key}


#: `_all_refused` found no rows under the key it was given while the receipt
#: held rows under others. Reported rather than returned as "": the lookup is
#: the thing that failed, and saying "it ran fine" would be a guess.
NO_ROWS_FOR_CANDIDATE = "no rows under that name in the receipt"


def _all_refused(rows, candidate: str) -> str:
    """The failure class, when EVERY row for `candidate` never reached a model.

    Empty when any row actually reached a model, because then the candidate
    really was measured and a low score is its own.

    MATCHED ON THE RECEIPT KEY, which is what the rows carry. A bare repo id
    matches nothing for an engine lane, where the key is `mflux/<id>-q8`, and
    "matched nothing" used to return "" -- the same answer as "it ran" -- so a
    mis-keyed lookup silently disabled the guard instead of failing. A safety
    check whose lookup miss looks like a pass is worse than no check.
    """
    mine = [r for r in rows or [] if r.get("candidate") == candidate]
    if not mine:
        # No rows at all is a different fact and the caller handles it; no
        # rows for THIS candidate when others have some is a key mismatch.
        return "" if not rows else NO_ROWS_FOR_CANDIDATE
    seen = {r.get("failure_class") or "" for r in mine}
    return sorted(seen)[0] if seen <= set(reasons.NEVER_RAN) else ""


def _receipt_at(out, conn=None) -> dict | None:
    """The stored run for the directory this invocation named. #222, #410.

    The only way to know which run a receipt describes is to have named it.
    """
    from harness import runs
    with runs.store(conn) as c:
        return runs.receipt_at(c, out)


def _report_sweep(a) -> int:
    """Read EVERY source, then report. What "run a discovery" should mean.

    `--feeds` refreshes the eight feeds and leaves github-crowd untouched,
    because only the --neighbors path calls record_fetch for it. So a sweep
    that ran feeds alone left the star graph -- the source measured as this
    project's best, and the one with zero overlap with the feeds -- nine days
    stale while reporting success. Issue #187.
    """
    rc = 0
    for tier in SOURCE_TIERS:
        # Each report reads its own flags off the namespace, so the flag being
        # dispatched on has to be the one that is set.
        flags = {t: t == tier for t in SOURCE_TIERS}
        sub = argparse.Namespace(**{**vars(a), **flags, "sweep": False})
        if not a.json:
            print(f"\n=== {tier} ===")
        rc = cmd_discover(sub) or rc
    return rc


def _report_feeds(a) -> int:
    from harness import memory_store as ms
    store = ms.connect()
    try:
        found = discovery.from_feeds(
            verify=not a.no_verify,
            min_relevance=1 if a.platform else None, store=store,
            comments=getattr(a, "comments", 0),
            mentions=(_mention_extractor()
                      if getattr(a, "comments", 0) and getattr(a, "judge", False)
                      else None))
        if getattr(a, "judge", False):
            found = _judge_proposals(found, store)
    finally:
        store.close()
    if a.json:
        print(json.dumps({"candidates": [vars(c) for c in found]}, indent=2))
        return 0
    broken = [c for c in found if c.blocked]
    for c in broken:
        err(f"{c.name}: {c.blocked}")
    found = [c for c in found if not c.blocked]
    if not found:
        print("nothing new in the feeds, or no network.")
        return 0
    updates = [c for c in found if c.kind == "update"]
    found = [c for c in found if c.kind != "update"]
    if updates:
        print("\nBEHIND on something already installed:")
        for c in updates:
            print(f"  {c.name:12} {c.note}")
            print(f"    -> {c.how}")
    if not found:
        return 0
    print("\ncandidates the community is talking about that nothing here "
          "has measured")
    print("(a popularity signal, not a measurement -- the eval decides)")
    for c in found:
        print(f"\n  {c.name}")
        print(f"    {c.source}")
        print(f"    {c.note}")
        print(f"    -> uv run python -m evals.run {c.how}")
    return 0


def _mention_extractor():
    """The judge, used to read names out of freeform comment prose. #79."""
    from harness import judge
    return lambda text: judge.mentions(text)


def _judge_proposals(found, store):
    """Score, record and re-sort. The cheapest tier: text only, no GPU."""
    from harness import judge
    from harness import memory_store as ms
    try:
        rubric = judge.load()
    except judge.JudgeError as exc:
        err(str(exc))
        return found
    for c in found:
        if c.kind != "proposal":
            continue
        try:
            score, why = judge.score(
                judge.describe(c.name, why=c.note, relevance=c.relevance),
                rubric)
        except Exception as exc:  # noqa: BLE001
            err(f"{c.name}: {exc}")
            continue
        c.relevance = score
        c.note = f"[{score}/10] {why[:90]} | {c.note}"
        try:
            ms.decide(store, c.name, "queued", tier="judge", score=score,
                      rubric=rubric.stamp, judge=rubric.model, detail=why[:200],
                      reason=reasons.CANDIDATE)
        except (KeyError, ms.IllegalTransition):
            pass
    found.sort(key=lambda c: -getattr(c, "relevance", 0))
    return found


def cmd_voices(a) -> int:
    """Three coupled settings behind one name is only usable if the names are
    discoverable."""
    def star(name):
        return " (default)" if name == audio.DEFAULT_VOICE else ""

    note("cloned (a reference clip, so any language, any accent):")
    for name in sorted(audio.VOICE_PRESETS):
        v = audio.resolve_voice(name)
        note(f"  {name}{star(name)}  {v.model.split('/')[-1]}"
             f"  speaks {v.lang_code}  from {Path(v.ref_audio).name}")
    note("\nkokoro (a fixed table, English unless noted; sub-second, "
         "where a cloned voice takes seconds):")
    for name in audio.KNOWN_VOICES:
        extra = "  French, female" if name == "ff_siwis" else ""
        note(f"  {name}{star(name)}{extra}")
    emit(default=audio.DEFAULT_VOICE, cloned=sorted(audio.VOICE_PRESETS),
         kokoro=list(audio.KNOWN_VOICES))
    return 0


def cmd_sensitivity(a) -> int:
    """Vary a constant and say whether anything downstream moved."""
    from harness import probes, sensitivity

    if getattr(a, "list", False):
        if a.json:
            print(json.dumps({"probes": sorted(probes.PROBES),
                              "uncovered": probes.UNCOVERED}, indent=2))
            return 0
        print("\nprobes:")
        for name in sorted(probes.PROBES):
            print(f"  {name}")
        print("\nnot covered, and why:")
        for name, why in sorted(probes.UNCOVERED.items()):
            print(f"  {name}\n      {why}")
        return 0

    unknown = [n for n in a.names if n not in probes.PROBES]
    if unknown:
        return err(f"unknown probe(s) {', '.join(unknown)}; "
                   f"known: {', '.join(sorted(probes.PROBES))}")
    try:
        found = probes.run(a.names or None)
    except Exception as exc:  # noqa: BLE001
        return err(f"{exc}")
    if a.json:
        print(json.dumps({"coverage": probes.coverage(),
                          "findings": [
                              {"name": f.name, "default": f.default,
                               "verdict": f.verdict, "band": list(f.band),
                               "readings": [vars(r) for r in f.readings]}
                              for f in found]}, indent=2, default=str))
        return 0
    cover = probes.coverage()
    print(f"\nagainst cached data only: a crowd of {cover['crowd']} and "
          f"{cover['clones']} clones on disk\n")
    print(sensitivity.report(found))
    return 0


def cmd_hear(a) -> int:
    clip = Path(a.file) if a.file else Path(a.output or
                                            default_output("clip", ".wav"))
    if not a.file:
        clip.parent.mkdir(parents=True, exist_ok=True)
        print(f"listening for {a.seconds}s...", file=sys.stderr)
        try:
            r = proc.run(audio.record_argv(clip, a.seconds),
                         timeout=a.seconds + 30)
        except FileNotFoundError:
            return err("`rec` not found. Install it with: brew install sox")
        if not r.ok:
            return err(f"recording failed (exit {r.returncode})\n{r.stderr.strip()}")

    try:
        text = audio.transcribe(clip, base_url=a.base_url)
    except audio.AudioError as exc:
        return err(str(exc))
    return say(path=clip, body=text, human=text)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="soh", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command")

    def media(name, help_, engine_default, func):
        p = sub.add_parser(name, help=help_)
        p.add_argument("prompt")
        p.add_argument("-o", "--output")
        p.add_argument("-m", "--model", default=engine_default,
                       help="engine spec, e.g. mflux:z-image-turbo,quantize=4")
        p.add_argument("--width", type=int, default=DEFAULT_RESOLUTION)
        p.add_argument("--height", type=int, default=DEFAULT_RESOLUTION)
        p.add_argument("--steps", type=int)
        p.add_argument("--seed", type=int)
        p.set_defaults(func=func)
        return p

    media("image", "generate an image", DEFAULT_IMAGE_ENGINE, cmd_image)
    v = media("video", "generate a video", DEFAULT_VIDEO_ENGINE, cmd_video)
    v.add_argument("--frames", type=int)
    v.add_argument("--seconds", type=int, help="duration at 24fps")

    for name, help_, func in (("svg", "generate an SVG", cmd_svg),
                              ("web", "generate a web page", cmd_web)):
        p = sub.add_parser(name, help=help_)
        p.add_argument("prompt")
        p.add_argument("-o", "--output")
        p.add_argument("-m", "--model",
                       default=DEFAULT_SVG_MODEL if name == "svg"
                       else DEFAULT_WEB_MODEL,
                       help="gateway alias")
        p.add_argument("--gateway", default=completion.DEFAULT_GATEWAY)
        p.set_defaults(func=func)
        if name == "svg":
            # `llm` is still the default because it is seconds against a
            # minute, and for a two-shape icon it is sometimes enough. `trace`
            # is the one that draws the picture.
            p.add_argument("--method", choices=("llm", "trace", "icon"),
                           default="llm",
                           help="llm: a language model writes the paths. "
                                "trace: generate an image and vectorize it. "
                                "icon: the same, tuned for a small file")
            p.add_argument("--engine", default=DEFAULT_IMAGE_ENGINE,
                           help="image engine used by --method trace")
            p.add_argument("--width", type=int, default=512)
            p.add_argument("--height", type=int, default=512)
            p.add_argument("--seed", type=int)

    pr = sub.add_parser("prompt",
                        help="write a prompt for whatever engine this machine "
                             "runs in a lane")
    pr.add_argument("lane", choices=["image", "video"],
                    help="which generating lane the prompt is for")
    pr.add_argument("about", nargs="?", default="",
                    help="what the caller wants. Without it, print the guide")
    pr.add_argument("-m", "--model", default=DEFAULT_EXTRACT_MODEL,
                    help="gateway alias that writes the prompt")
    pr.add_argument("--gateway", default=completion.DEFAULT_GATEWAY)
    pr.add_argument("--quiet", action="store_true",
                    help="omit the engine and guide line from stderr")
    pr.set_defaults(func=cmd_prompt)

    c = sub.add_parser("code", help="generate code")
    c.add_argument("prompt")
    c.add_argument("-o", "--output", help="write to a file instead of stdout")
    c.add_argument("-m", "--model", default=DEFAULT_CODE_MODEL,
                   help="gateway alias")
    c.add_argument("--gateway", default=completion.DEFAULT_GATEWAY)
    c.set_defaults(func=cmd_code)

    x = sub.add_parser("extract",
                       help="answer a question about a file or piped input")
    x.add_argument("prompt", help="the question")
    x.add_argument("-f", "--file", help="the material; omit to read stdin")
    x.add_argument("-o", "--output", help="write to a file instead of stdout")
    x.add_argument("-m", "--model", default=DEFAULT_EXTRACT_MODEL,
                   help="gateway alias")
    x.add_argument("--gateway", default=completion.DEFAULT_GATEWAY)
    x.set_defaults(func=cmd_extract)

    s = sub.add_parser("say", help="speak text aloud")
    s.add_argument("text", help="the text, or - to read stdin")
    s.add_argument("-o", "--output")
    s.add_argument("--voice", default=audio.DEFAULT_VOICE,
                   help="a cloned preset or a kokoro voice; see `soh voices`")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--base-url", default=audio.DEFAULT_BASE_URL)
    s.add_argument("--no-play", dest="play", action="store_false", default=True)
    s.set_defaults(func=cmd_say)

    sub.add_parser("voices", help="list the voices that can be spoken"
                   ).set_defaults(func=cmd_voices)

    d = sub.add_parser("discover",
                       help="what this machine can do, and what has never "
                            "been measured")
    d.add_argument("--lane", help="only this modality")
    d.add_argument("--gap", action="store_true",
                   help="only what has never been run")
    d.add_argument("--external", action="store_true",
                   help="ask the registries what exists that this machine has "
                        "never measured (needs --lane)")
    d.add_argument("--budget-gib", type=float, default=20.0, dest="budget_gib",
                   help="with --loop --run, the ceiling on what this "
                        "invocation will download")
    d.add_argument("--repeat", type=int, default=3,
                   help="with --loop --run, repetitions per case when "
                        "measuring a challenger against the incumbent")
    d.add_argument("--loop", action="store_true",
                   help="every step from a sweep to an adopted winner. Says "
                        "what it would do; --run spends the disk and minutes")
    d.add_argument("--sweep", action="store_true",
                   help="read every source family, then report. What running "
                        "a discovery means: --feeds alone leaves the star "
                        "graph unread")
    d.add_argument("--feeds", action="store_true",
                   help="read the community aggregation feeds for candidates")
    d.add_argument("--sources", action="store_true",
                   help="list discovery sources, when each was last read, and "
                        "any new sources the feeds point at")
    d.add_argument("--judge", action="store_true",
                   help="with --feeds, score each proposal 1-10 with the "
                        "rubric before anything is run")
    d.add_argument("--control", action="store_true",
                   help="score items whose outcome is already known, and report "
                        "whether the rubric separates them. Run this before "
                        "trusting any score")
    d.add_argument("--shape", default="", choices=["", "described", "bare",
                                                   "carded"],
                   help="which known set the control scores. A tier must gate "
                        "on the shape of its own input: `described` is "
                        "hand-written project prose, `carded` is what a "
                        "registry says, `bare` is a name and nothing else")
    d.add_argument("--runs", type=int, default=3,
                   help="how many times to run the control. The judge samples "
                        "and nothing pins a seed, so one run is one draw")
    d.add_argument("--no-control", action="store_true",
                   help="with --judge --from-store, score without running the "
                        "control first. For a person watching the output, "
                        "never for a Job")
    d.add_argument("--gateway", default=completion.DEFAULT_GATEWAY,
                   help="where the judge model is served. A pod reaches the "
                        "host's gateway, not its own localhost")
    d.add_argument("--neighbors", action="store_true",
                   help="repos concentrated in the crowd that builds what "
                        "this machine runs; add --control to check the metric "
                        "before trusting it")
    d.add_argument("--crowd", type=int, default=250,
                   help="with --neighbors, how many people to ask")
    d.add_argument("--budget", type=int, default=900,
                   help="with --neighbors, cap on GitHub API requests")
    d.add_argument("--top", type=int, default=25,
                   help="with --neighbors, how many to show")
    d.add_argument("--inspect", action="store_true",
                   help="clone a candidate's source and say whether it can run "
                        "here, before anything is downloaded")
    d.add_argument("--repos", nargs="*", default=[],
                   help="with --inspect, specific repos instead of the crowd")
    d.add_argument("--from-store", action="store_true",
                   help="with --inspect, take candidates the sweep already "
                        "found and nothing has answered, most-corroborated "
                        "first, instead of rebuilding the crowd. With --judge "
                        "and without --inspect, score what the source tier "
                        "queued and no judge has read")
    d.add_argument("--shard", default="", metavar="I/N",
                   help="with --inspect, take only this worker's slice of the "
                        "candidates. Kubernetes passes the index of an Indexed "
                        "Job; without it every worker does the same work")
    d.add_argument("--coverage", action="store_true",
                   help="of the things this machine runs, which a configured "
                        "source ever surfaced. Precision measures what is "
                        "caught; this measures reach")
    d.add_argument("--winners", action="store_true",
                   help="what the stored runs say won each lane, against the "
                        "defaults this CLI has typed in")
    d.add_argument("--screen", action="store_true",
                   help="run the cheapest real thing on the top of the queue "
                        "and record whether it ran at all. Says what it would "
                        "do unless given --run, and NEVER downloads")
    d.add_argument("--run", action="store_true",
                   help="with --screen, actually run it")
    d.add_argument("--limit", type=int, default=1,
                   help="with --screen --run, how many to screen. One at a "
                        "time: a screen holds a model in memory")
    d.add_argument("--queue", action="store_true",
                   help="what a screen would teach us, best first, from what "
                        "the store already knows. Arithmetic, not a judge")
    d.add_argument("--recurrence", action="store_true",
                   help="what keeps coming back, from the discovery store")
    d.add_argument("--evidence", action="store_true",
                   help="verdicts whose run receipt is no longer on disk, so "
                        "nothing can re-judge them")
    d.add_argument("--requeue", action="store_true",
                   help="with --revisit, retract each one back to inspect")
    d.add_argument("--revisit", action="store_true",
                   help="candidates another machine refused whose reason no "
                        "longer applies here. A verdict is a fact about the "
                        "machine that made it")
    d.add_argument("--comments", type=int, default=0, metavar="N",
                   help="with --feeds, also read the replies on the N newest "
                        "posts per source. The comparative judgements live "
                        "there, not in the post")
    d.add_argument("--platform", action="store_true",
                   help="with --feeds, only what looks like it runs on "
                        "THIS machine")
    d.add_argument("--no-verify", action="store_true",
                   help="with --feeds, skip resolving prose names against the "
                        "registry. Faster, and QUIETER: every unresolved name "
                        "is dropped rather than offered")
    d.set_defaults(func=cmd_discover)

    f = sub.add_parser("fetch",
                       help="download weights the inspect tier queued")
    f.add_argument("--run", action="store_true",
                   help="actually download; without it, only says what would")
    f.add_argument("--limit", type=int, default=1,
                   help="how many to fetch. One at a time by default: this "
                        "machine holds one working set")
    f.set_defaults(func=cmd_fetch)

    rep = sub.add_parser(
        "report",
        help="one self-contained HTML page showing where the harness stands")
    rep.add_argument("--out", default="",
                     help="where to write it (default: $LOCALHARNESS_HOME/report.html)")
    rep.add_argument("--export", action="store_true",
                     help="write this machine's report as privacy-checked JSON "
                          "(default: $LOCALHARNESS_HOME/reports/<machine>.json)")
    rep.add_argument("--publish", action="store_true",
                     help="publish that JSON to the reports branch and rebuild "
                          "the GitHub Pages site")
    rep.add_argument("--auto-publish", choices=["on", "off"], default="",
                     help="publish at the end of every discovery loop on this "
                          "machine; off until turned on")
    rep.set_defaults(func=cmd_report)

    rub = sub.add_parser(
        "rubric",
        help="label an eval set by hand and score local models on it. #286")
    rub.add_argument("action", choices=["label", "status", "run"])
    rub.add_argument("set", help="eval set directory, or a name under "
                                 "$LOCALHARNESS_HOME/evalsets")
    rub.add_argument("--candidates", default="",
                     help="with run, comma-separated gateway aliases")
    rub.add_argument("--gateway", default=completion.DEFAULT_GATEWAY)
    rub.add_argument("--port", type=int, default=8766)
    rub.add_argument("--repeat-rate", type=float, default=0.2)
    rub.add_argument("--no-browser", action="store_true")
    rub.set_defaults(func=cmd_rubric)

    thr = sub.add_parser("throughput", help="requests per hour at several "
                         "in-flight levels against one gateway alias")
    thr.add_argument("--model", required=True)
    thr.add_argument("--texts", required=True,
                     help="JSONL file; each line's --field is one request")
    thr.add_argument("--field", default="text")
    thr.add_argument("--n", type=int, default=16)
    thr.add_argument("--levels", default="1,2,4")
    thr.add_argument("--max-tokens", type=int, default=300)
    thr.add_argument("--gateway", default="http://127.0.0.1:4000")
    thr.set_defaults(func=cmd_throughput)
    dsk = sub.add_parser("disk", help="what the weights cache holds, what "
                         "uses it, and what is safe to delete")
    dsk.add_argument("--delete", choices=("rejected", "unknown"), default="",
                     help="remove this group, only what is safe to delete")
    dsk.add_argument("--yes", action="store_true",
                     help="do not ask; required with --json")
    dsk.add_argument("--record", action="store_true",
                     help="give every path with no download row a row, and "
                          "stamp rows whose path is gone as removed")
    dsk.set_defaults(func=cmd_disk)
    mem = sub.add_parser("memory", help="measure how much memory a run can "
                         "take before macOS starts pushing back")
    mem.add_argument("action", choices=("ramp", "show"))
    mem.add_argument("--step-gb", type=float, default=1.0)
    mem.add_argument("--settle", type=float, default=3.0,
                     help="seconds to wait after each step before sampling")
    mem.add_argument("--floor-pct", type=int, default=10,
                     help="stop if kern.memorystatus_level falls to this")
    mem.add_argument("--cap-gb", type=float, default=None,
                     help="never allocate more than this; default RAM - 4 GB")
    mem.set_defaults(func=cmd_memory)
    jobs = sub.add_parser("jobs", help="the work queue: runs in order while "
                          "nobody is using this machine")
    jobs.add_argument("action", choices=("add", "list", "pause", "resume",
                                         "cancel", "priority"))
    jobs.add_argument("rest", nargs=argparse.REMAINDER,
                      help="add: -- <command...>; cancel: <id>")
    jobs.add_argument("--title", default="")
    jobs.add_argument("--priority", type=int, default=0,
                      help="higher runs first; ties run in the order added")
    jobs.set_defaults(func=cmd_jobs)
    jud = sub.add_parser(
        "judge",
        help="decide a human-judged lane by looking and listening. Issue #273")
    # THE RUN DIRECTORY IS REQUIRED, never a newest receipt. That helper
    # says so itself: "NOT FOR DECIDING ANYTHING. Reporting only", because
    # newest means sorts-highest-by-name and one badly named directory wins
    # forever (#222). A human verdict decides something.
    jud.add_argument("run", help="the run directory whose artifacts to compare")
    jud.add_argument("--lane", default="",
                     help="the lane being judged (default: read from the "
                          "receipt)")
    jud.add_argument("--port", type=int, default=8765)
    jud.add_argument("--no-browser", action="store_true")
    jud.set_defaults(func=cmd_judge)

    ver = sub.add_parser(
        "verify",
        help="run each lane's OWN default, to find out whether the lane works")
    ver.add_argument("--lane", default="", help="only this lane")
    ver.add_argument("--run", action="store_true",
                     help="actually run; without it, only says what it would")
    ver.add_argument("--all", action="store_true",
                     help="every lane, not only the unverified and stale ones")
    ver.set_defaults(func=cmd_verify)

    sens = sub.add_parser(
        "sensitivity",
        help="does a constant change anything? Issue #98")
    sens.add_argument("names", nargs="*",
                      help="probes to run (default: all). "
                           "`--list` names them")
    sens.add_argument("--list", action="store_true",
                      help="name the probes and the constants nothing covers")
    sens.set_defaults(func=cmd_sensitivity)

    h = sub.add_parser("hear", help="transcribe a clip, or record and transcribe")
    h.add_argument("file", nargs="?", help="an existing audio file")
    h.add_argument("-o", "--output", help="where to save a new recording")
    h.add_argument("--seconds", type=float, default=5.0)
    h.add_argument("--base-url", default=audio.DEFAULT_BASE_URL)
    h.set_defaults(func=cmd_hear)

    # On EVERY verb. A flag that only some subcommands accept is worse than no
    # flag: the caller cannot rely on it without first knowing which.
    for parser in sub.choices.values():
        parser.add_argument("--json", action="store_true",
                            help="machine-readable result on stdout, including "
                                 "on failure")
    return ap


def main(argv: list[str] | None = None) -> int:
    global _JSON, _VERB
    ap = build_parser()
    a = ap.parse_args(argv)
    _JSON = bool(getattr(a, "json", False))
    _VERB = getattr(a, "command", "") or ""
    # Before anything spawns mflux or h3. Installed on PATH this runs with
    # nothing sourced, and an unset HF_HOME sends huggingface_hub to
    # ~/.cache/huggingface to re-download weights that are already on the
    # volume. Silently, and onto the disk this machine has least of.
    env.guard()
    if not getattr(a, "func", None):
        ap.print_help(sys.stderr)
        return 2
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
