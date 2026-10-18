"""What a claude-code arm carries beside its model: none, skill:<name>, prompt:<template> or placebo:<context>. #995."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

KINDS = ("none", "skill", "prompt", "placebo")
#: Planted skills (the known-answer control), read before the home's skills.
PLANTED = Path(__file__).with_name("arm_contexts.yaml")
#: How a skill or placebo text reaches the model: the same frame for both, so only the words differ.
FRAME = "<context>\n{text}\n</context>\n\n{task}"
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_SLOT = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
#: Sentences that tell a coder nothing; the placebo cycles them to the length it must match.
FILLER = (
    "The reading room of the old county library has tall windows that face east.",
    "In the morning the light falls across the long oak tables and the worn floor.",
    "The shelves are numbered by hand in a careful, slightly slanted script.",
    "A clock above the door has run a few minutes slow for as long as anyone remembers.",
    "Visitors sign a ledger at the front desk, and most of them write in pencil.",
    "On wet days the radiators tick and the room smells faintly of paper and wool.",
    "A row of potted ferns lines the sill, watered every Tuesday by the same volunteer.",
    "The card catalogue is still there, though nobody has opened a drawer in years.",
)


def skills_root() -> Path:
    """The home's Claude Code skills, read at call time."""
    return Path.home() / ".claude" / "skills"


@dataclass(frozen=True)
class Context:
    spec: str
    kind: str
    name: str = ""
    #: The text put before the task (skill or placebo); "" for none and prompt.
    text: str = ""
    #: A prompt template's steps (methods.Step); () for every other kind.
    steps: tuple = ()
    digest: str = ""
    #: Characters of instruction this context adds; a placebo matches it.
    chars: int = 0
    source: str = ""

    def prompt(self, task: str) -> str:
        """The single message for a context that is text before the task."""
        return FRAME.format(text=self.text, task=task) if self.text else task

    def as_receipt(self) -> dict:
        return {"spec": self.spec, "kind": self.kind, "name": self.name, "digest": self.digest,
                "chars": self.chars, "source": self.source}


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def planted() -> dict[str, dict]:
    import yaml
    data = yaml.safe_load(PLANTED.read_text(encoding="utf-8")) or {}
    return {str(r["name"]): r for r in data.get("skills") or []}


def skill_text(name: str) -> tuple[str, str]:
    """(text, source) of a skill as a session loads it: the SKILL.md body without its frontmatter."""
    row = planted().get(name)
    if row is not None:
        return str(row["text"]).strip(), f"planted:{PLANTED.name}"
    path = skills_root() / name / "SKILL.md"
    if not path.is_file():
        raise ValueError(f"skill:{name}: no planted skill and no {path}")
    body = _FRONTMATTER.sub("", path.read_text(encoding="utf-8"), count=1).strip()
    if not body:
        raise ValueError(f"skill:{name}: {path} has no body")
    home = str(Path.home())
    return body, str(path).replace(home, "~", 1)


def placebo(chars: int) -> str:
    """Exactly `chars` characters of FILLER: as long as what it controls for, and useless."""
    out, i = "", 0
    while len(out) < chars:
        out += ("" if not out else " ") + FILLER[i % len(FILLER)]
        i += 1
    return out[:chars].rstrip().ljust(chars, ".")


def parse(spec: str) -> Context:
    """The context a spec names. ValueError naming the spec for anything that would not run."""
    spec = (spec or "none").strip()
    kind, _, name = spec.partition(":")
    if kind not in KINDS:
        raise ValueError(f"context {spec!r}: the kind must be one of {', '.join(KINDS)}")
    if kind == "none":
        if name:
            raise ValueError("context none takes no name")
        return Context("none", "none")
    if not name:
        raise ValueError(f"context {spec!r} needs a name: {kind}:<name>")
    if kind == "skill":
        text, source = skill_text(name)
        return Context(spec, kind, name, text=text, digest=_digest(text), chars=len(text), source=source)
    if kind == "prompt":
        from harness import methods
        method = methods.REGISTRY.get(name)
        steps = (method.extra.get("steps") if method else None) or ()
        if not steps:
            raise ValueError(f"context {spec!r}: {name} is not a template in {methods.TEMPLATES.name}")
        chars = sum(len(_SLOT.sub("", s.prompt).strip()) for s in steps)
        return Context(spec, kind, name, steps=tuple(steps), digest=method.extra["digest"], chars=chars,
                       source=f"template:{methods.TEMPLATES.name}")
    inner = parse(name)
    if inner.kind in ("none", "placebo"):
        raise ValueError(f"context {spec!r}: a placebo matches a skill or prompt, not {inner.kind}")
    text = placebo(inner.chars)
    return Context(spec, kind, name, text=text, digest=_digest(text), chars=len(text),
                   source=f"placebo of {inner.spec} {inner.digest}")


def key(model_key: str, spec: str) -> str:
    """The receipt key of an arm: the model's, plus its context unless none."""
    ctx = (spec or "none").strip()
    return model_key if ctx == "none" else f"{model_key},context={ctx}"
