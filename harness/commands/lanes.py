"""The lane verbs: image, video, prompt, svg, web, code, extract, decide, say, voices, hear, sensitivity."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

from harness import audio, completion, exclusive, proc, vector
from harness.checks import (code as code_check, html as html_check,
    image as image_check, svg as svg_check)
from harness.engines import resolve
from harness.commands.common import default_output, emit, err, note, say


# Named per engine family because the fix differs, and because `uv tool install
# mflux` on its own silently picks Python 3.9, where every mflux entry point
# dies on `int | None`. The tell is 2 executables installed instead of 37.
INSTALL_HINT = {
    "mflux": " Install it with: uv tool install --python 3.12 mflux",
    "h3": " Build it: git clone https://github.com/antirez/h3.c && make -C h3.c",
}


def lane_model(lane: str, chosen: str | None = None) -> str:
    """-m when given, else the lane's adopted model here, else its typed constant. #297."""
    from harness import delegate
    return delegate.lane_model(lane, chosen)


def _text_route(a, lane: str):
    """(spec, serving.Route) for a text lane command; raises ValueError. #297."""
    from harness import delegate
    return delegate.route(lane, getattr(a, "model", None),
                          getattr(a, "gateway", None) or "")


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
    return _generate(lane_model("image", a.model), a.prompt, a.output, params)


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
        spec, where = _text_route(a, "extract")
        got = completion.complete(ask, model=where.model, gateway=where.base,
                                  modality="extract",
                                  sampling=where.sampling or None)
    except Exception as exc:  # noqa: BLE001
        return err(f"{exc}")
    note(got.strip())
    if not a.quiet:
        # The provenance goes to stderr so the prompt itself can be piped.
        print(f"[{engine.name}, guide {guide['identity']}, written by {spec}]",
              file=sys.stderr)
    emit(prompt=got.strip(), lane=a.lane, engine=engine.name,
         guide=guide["identity"], model=spec)
    return 0


def cmd_video(a) -> int:
    params = {k: getattr(a, k) for k in
              ("width", "height", "frames", "seconds", "steps", "seed")}
    return _generate(lane_model("video", a.model), a.prompt, a.output, params)


def _text(a, modality: str, suffix: str, checker) -> int:
    try:
        _, where = _text_route(a, modality)
        raw = completion.complete(a.prompt, model=where.model, gateway=where.base,
                                  modality=modality,
                                  sampling=where.sampling or None)
    except (ValueError, completion.CompletionError) as exc:
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
    rc = _generate(lane_model("image", a.engine), f"{a.prompt}, {TRACE_STYLE}", png,
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
        _, where = _text_route(a, modality)
        raw = completion.complete(a.prompt, model=where.model, gateway=where.base,
                                  modality=modality, context=context,
                                  sampling=where.sampling or None)
    except (ValueError, completion.CompletionError) as exc:
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


def cmd_decide(a) -> int:
    """Answer a flat schema's fields with a probability per choice. #297, #423."""
    from harness import delegate
    raw = a.schema
    try:
        if not raw.lstrip().startswith("{"):
            raw = Path(raw).read_text(encoding="utf-8")
        schema = delegate.check_schema(json.loads(raw))
        context = ""
        if a.file:
            context = Path(a.file).read_text(encoding="utf-8")
        elif not sys.stdin.isatty():
            context = sys.stdin.read()
        _, where = _text_route(a, "decide")
        body, _ = delegate.ask(a.prompt, schema, where, context=context)
    except (OSError, ValueError, completion.CompletionError) as exc:
        return err(str(exc))
    return say(body=body, human=json.dumps(body))


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
                       base_url=a.base_url, model=getattr(a, "model", None) or "")
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
        text = audio.transcribe(clip, base_url=a.base_url,
                                model=getattr(a, "model", None) or "")
    except audio.AudioError as exc:
        return err(str(exc))
    return say(path=clip, body=text, human=text)
