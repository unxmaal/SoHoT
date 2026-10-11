"""The Knob record and the names every area module of the registry builds knobs from (#636, #751)."""
from __future__ import annotations

from dataclasses import dataclass

from harness import completion

GIB = 1024 ** 3

#: The until-predicate family a knob's limit is written in: `limit:name>N` or a machine fact `name:>N`.
LIMIT, MACHINE = "limit", "machine"

#: The lanes an eval asks for a text reply, the ones a reply budget is set for.
TEXT_LANES = tuple(completion.BUDGET)
#: The lanes whose replies go through the text runner's request and load timeouts; agent steps have their own.
REQUEST_LANES = tuple(lane for lane in TEXT_LANES if lane != "agent")


def _lane_values(got) -> tuple:
    items = got.items() if isinstance(got, dict) else got
    return tuple((lane, tuple(v)) for lane, v in sorted(items))


@dataclass(frozen=True)
class Knob:
    name: str
    #: "rel:NAME" or "rel:func(param)"; the first is the value swept, a second is the fallback a table falls back to.
    sites: tuple[str, ...]
    values: tuple
    lanes: tuple[str, ...] = ()
    #: The predicate name that shows this knob binding; "{lane}" is replaced per lane.
    limit: str = ""
    predicate: str = LIMIT
    #: The recorded limit is the value divided by this.
    scale: float = 1.0
    probe: str = ""
    #: Where an eval's receipt records it: "max_tokens" (its own field), "knobs" (Receipt.knobs), or "" (not the exam).
    receipt: str = ""
    #: The runner attribute a run sets for an override; "" rebinds the first site for the run instead.
    runner_attr: str = ""
    note: str = ""
    #: lane -> the range swept there, where a lane's default sits outside `values`. #654.
    lane_values: tuple = ()
    #: The value receipts written before this knob was recorded on them ran at; None if it always was. #693.
    unrecorded: object = None
    #: What a dict first site is keyed by: "lane", or "machine" (power.machine_key()).
    keyed: str = "lane"

    def __post_init__(self):
        for field in ("sites", "values", "lanes"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        object.__setattr__(self, "lane_values", _lane_values(self.lane_values))

    def default(self, lane: str = ""):
        from harness.knobs import resolve
        got = resolve(self.sites[0])
        if isinstance(got, dict):
            key = lane
            if self.keyed == "machine":
                from harness import power
                key = power.machine_key()
            if key in got:
                return got[key]
            return resolve(self.sites[1]) if len(self.sites) > 1 else None
        return got

    def values_for(self, lane: str = "") -> tuple:
        return dict(self.lane_values).get(lane, self.values)

    def limit_name(self, lane: str = "") -> str:
        if "{lane}" not in self.limit:
            return self.limit
        return self.limit.format(lane=lane) if lane else self.limit.split(".{lane}")[0]

    def limit_value(self, lane: str = ""):
        got = self.default(lane)
        return got / self.scale if self.scale != 1.0 else got


def _k(name, sites, values, lane_values=None, **kw) -> tuple[str, Knob]:
    return name, Knob(name, sites, values, lane_values=lane_values or (), **kw)
