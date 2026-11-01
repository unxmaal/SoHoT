"""The checker that keeps one person's desk out of a public repo. Issue #136.

The interesting assertions are the NEGATIVE ones. A checker that flags every
mention of hardware would be turned off within a week, and the rule this
project actually wants is narrower: a measurement keeps its instrument, and
the household around it goes.
"""
import re
from pathlib import Path

import pytest

from harness import github, privacy


def scan(text):
    return [f.name for f in privacy.scan(text, "t")]


# ---- what must be caught ---------------------------------------------------

@pytest.mark.parametrize("text,name", [
    ("export HF_ROOT=/Volumes/Models/hf", "named-volume"),
    ("weights sat on /Volumes/BigDisk", "named-volume"),
    ("claude mcp add http://kitchen-mac.local:8899/mcp", "private-host"),
    ("the gateway answered on 192.168.1.42:4000", "private-host"),
    ("Linux on a spare NVMe in that same desktop", "spare-drive"),
    ("both halves live in the same tower", "same-box"),
    ("this box plays games and runs this sometimes", "gaming-box"),
    ("a gaming rig that quietly starts a language model", "gaming-box"),
    ("needs-cuda on the mini and needs-mlx on the card", "machine-nickname"),
    ("25.0 GiB of 32 on this mini", "machine-nickname"),
])
def test_the_household_is_caught(text, name):
    assert scan(text) == [name]


def test_a_home_directory_names_an_account():
    assert scan("/Users/somebody/projects/h3.c/h3") == ["home-path"]


# ---- what must NOT be caught, which is the harder half ---------------------

@pytest.mark.parametrize("text", [
    # A measurement keeps its instrument. This is the whole point.
    "Measured on the 4070, a request takes VRAM from 2462 to 3296 MiB",
    "Video takes about 40 minutes a generation on an M2 Pro with 32 GB",
    "the 61.6 GB of RAM behind a 12 GB 4070 is not budget",
    "| lane | Apple Silicon | NVIDIA, on Windows or Linux |",
    # Placeholders are the fix, so they must not read as the defect.
    "export HF_ROOT=/Volumes/FAST/hf",
    "HF_ROOT=/Volumes/NO_SUCH_VOLUME/hf walks up to the root",
    "claude mcp add --transport http lh http://<host>.local:8899/mcp",
    # Apple's own path, not a drive anyone named.
    "$ df -h /System/Volumes/Data",
    # Process co-location, not a floor plan. An early cut flagged this.
    "the client and the server run on the same machine",
    "~/.cache/huggingface is the fallback",
])
def test_provenance_and_placeholders_survive(text):
    assert scan(text) == []


# ---- the escape hatch ------------------------------------------------------

def test_a_marker_on_the_line_exempts_it():
    assert scan("HF_ROOT=/Volumes/Models/hf  # privacy-ok: quoting the old default") == []


def test_a_marker_on_the_line_above_exempts_it():
    """For a line that will not take a trailing comment -- a table row, a
    fenced transcript."""
    assert scan("<!-- privacy-ok -->\n| /Volumes/Models | 959 MB/s |") == []


def test_the_marker_does_not_leak_to_the_line_after_next():
    assert scan("# privacy-ok\nfine\n/Volumes/Models/hf") == ["named-volume"]


# ---- people's names are configured, never shipped --------------------------

def test_no_name_list_means_the_structural_patterns_still_run(tmp_path, monkeypatch):
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    assert privacy.name_pattern(tmp_path) is None


def test_names_come_from_the_environment_and_are_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("LH_PRIVATE_NAMES", "Ada, Grace")
    extra = privacy.name_pattern(tmp_path)
    assert [f.name for f in privacy.scan("grace picked this one by ear", "t", extra)] \
        == ["person-name"]


def test_names_come_from_an_untracked_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    (tmp_path / privacy.NAMES_FILE).write_text("Ada\nGrace\n", encoding="utf-8")
    extra = privacy.name_pattern(tmp_path)
    assert [f.name for f in privacy.scan("Ada's call, and a reasonable one", "t", extra)] \
        == ["person-name"]


def test_a_name_is_not_matched_inside_another_word(tmp_path, monkeypatch):
    """`\\b` matters: 'Ada' inside 'Adaptive' is not a person."""
    monkeypatch.setenv("LH_PRIVATE_NAMES", "Ada")
    extra = privacy.name_pattern(tmp_path)
    assert privacy.scan("an adaptive threshold", "t", extra) == []


def test_the_name_list_is_never_committed():
    """The checker would otherwise publish exactly what it exists to hide."""
    ignored = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert privacy.NAMES_FILE in ignored


# ---- the repo itself -------------------------------------------------------

def test_the_checker_skips_its_own_fixtures():
    """These two files are FULL of the thing being detected, by necessity.
    CI caught this the hard way: locally the new test file was untracked, so
    `git ls-files` could not see it and lint passed; the same commit turned
    all three runners red the moment git knew about it."""
    assert "tests/test_harness_privacy.py" in privacy.SELF
    assert "harness/privacy.py" in privacy.SELF


def test_this_repo_is_clean():
    """`make lint` runs this too; here it fails with the list rather than a
    bare exit code."""
    found = privacy.scan_paths(Path(__file__).resolve().parent.parent)
    assert not found, "\n" + "\n".join(str(f) for f in found)


# ---- a protocol constant is not an address --------------------------------

def test_the_kubernetes_dns_suffix_is_not_a_lan_address():
    """`svc.cluster.local` is byte-identical on every cluster on earth, so it
    identifies nobody. Flagging it would make the chart unlintable and teach
    the next person to switch the scanner off, which is the failure mode a
    detector dies of."""
    assert scan("host: postgres.localharness.svc.cluster.local") == []


def test_a_real_mdns_host_is_still_caught():
    """The negative control for the carve-out. Narrowing a rule is how a rule
    stops working, so the thing it was written for must still fire."""
    assert scan("url: http://basement.local:8899/mcp") == ["private-host"]


# ---- the tracker, before and after posting (#1296) -------------------------

FAKE_NAME = "Zorblax Quentaro"


class FakeGitHub:
    """Issue and PR listings, paged comment listings and edit histories; records every call, reaches nothing."""

    def __init__(self, comments=(), review_comments=(), per_page=None, edits=None):
        self.comments, self.review_comments = list(comments), list(review_comments)
        self.per_page, self.edits, self.calls = per_page or github.PER_PAGE, edits or {}, []

    def gh(self, *args):
        self.calls.append(args)
        return [{"number": 1, "title": "A clean issue", "body": "nothing to see"}] if args[0] == "issue" else []

    def api(self, path):
        self.calls.append(("api", path))
        rows = self.review_comments if "/pulls/comments" in path else self.comments
        page = int(path.rsplit("page=", 1)[1])
        return rows[(page - 1) * self.per_page:page * self.per_page]

    def graphql(self, number):
        self.calls.append(("graphql", number))
        return self.edits[number]


def comment(i, body, pr=False):
    kind = "pull" if pr else "issues"
    return {"id": 1000 + i, "html_url": f"https://github.com/o/r/{kind}/7#issuecomment-{1000 + i}", "body": body}


def _names(monkeypatch, tmp_path):
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    privacy.register([FAKE_NAME])
    return privacy.name_pattern(tmp_path)


def test_a_planted_name_in_a_comment_fails_the_scan(tmp_path, monkeypatch):
    fake = FakeGitHub(comments=[comment(1, "looks fine"), comment(2, f"{FAKE_NAME} measured it", pr=True)])
    found, counts = privacy.scan_github(extra=_names(monkeypatch, tmp_path), gh=fake.gh, api=fake.api)
    assert [(f.origin, f.name) for f in found] == [("pr#7 comment 1002", "person-name")]
    assert counts == {"issue": 1, "pr": 0, "comment": 2}


def test_a_clean_listing_passes(tmp_path, monkeypatch):
    fake = FakeGitHub(comments=[comment(1, "looks fine")], review_comments=[comment(2, "nit: rename", pr=True)])
    found, counts = privacy.scan_github(extra=_names(monkeypatch, tmp_path), gh=fake.gh, api=fake.api)
    assert found == [] and counts["comment"] == 2


def test_comments_are_read_past_the_first_page(tmp_path, monkeypatch):
    rows = [comment(i, "fine") for i in range(5)] + [comment(9, f"ask {FAKE_NAME}")]
    fake = FakeGitHub(comments=rows, per_page=2)
    monkeypatch.setattr(github, "PER_PAGE", 2)
    found, counts = privacy.scan_github(extra=_names(monkeypatch, tmp_path), gh=fake.gh, api=fake.api)
    assert [f.origin for f in found] == ["issue#7 comment 1009"] and counts["comment"] == 6
    assert ("api", "repos/{owner}/{repo}/issues/comments?per_page=2&page=3") in fake.calls


def test_posting_a_registered_name_is_refused_before_any_network_call(tmp_path, monkeypatch, capsys):
    _names(monkeypatch, tmp_path)
    ran = []
    monkeypatch.setattr(privacy.subprocess, "run", lambda *a, **kw: ran.append(a))
    body = tmp_path / "body.md"
    body.write_text(f"Thanks to {FAKE_NAME.lower()} for the trace.\n", encoding="utf-8")
    assert privacy.main(["gh", "issue", "comment", "5", "--body-file", str(body)]) == 1
    assert privacy.main(["gh", "pr", "create", "--title", "x", f"--body=from {FAKE_NAME}"]) == 1
    assert privacy.main(["gh", "issue", "create", "-t", f"{FAKE_NAME}'s idea", "-b", "fine"]) == 1
    assert ran == [] and "person-name" in capsys.readouterr().err


def test_a_clean_post_reaches_gh(tmp_path, monkeypatch):
    import io
    _names(monkeypatch, tmp_path)
    ran = []

    def run(argv, **kw):
        ran.append((argv, kw.get("input")))
        return privacy.subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(privacy.subprocess, "run", run)
    monkeypatch.setattr(privacy.sys, "stdin", io.StringIO("a plain body\n"))
    assert privacy.main(["gh", "issue", "comment", "5", "--body-file", "-"]) == 0
    assert ran == [(["gh", "issue", "comment", "5", "--body-file", "-"], "a plain body\n")]


def test_an_added_name_is_caught_by_the_next_scan(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    assert privacy.check_post(f"ask {FAKE_NAME}", root=tmp_path) == []
    assert privacy.main(["add", FAKE_NAME]) == 0
    assert [f.name for f in privacy.check_post(f"ask {FAKE_NAME}", root=tmp_path)] == ["person-name"]
    assert privacy.main(["add", FAKE_NAME]) == 0 and "already" in capsys.readouterr().out
    assert privacy.main(["add", "Zo"]) == 2


def test_an_edit_history_hit_is_reported_with_its_revision(tmp_path, monkeypatch):
    edits = {922: {"edits": [{"editedAt": "2026-10-26T15:02:38Z", "diff": "scrubbed"},
                             {"editedAt": "2026-10-17T12:22:54Z", "diff": f"run by {FAKE_NAME}"}],
                   "comments": [{"databaseId": 55, "edits": [{"editedAt": "2026-10-17T13:00:00Z",
                                                              "diff": "served from kitchen-mac.local"}]}]}}
    fake = FakeGitHub(edits=edits)
    found = privacy.scan_history([922], extra=_names(monkeypatch, tmp_path), graphql=fake.graphql)
    assert [(f.origin, f.name) for f in found] == [
        ("#922 edit 2026-10-17T12:22:54Z", "person-name"),
        ("#922 comment 55 edit 2026-10-17T13:00:00Z", "private-host")]


# ---- every tracked text format, read as its strings (#1455) ----------------

def _tree(tmp_path, monkeypatch, files: dict) -> list:
    monkeypatch.setenv("LH_PRIVATE_NAMES", FAKE_NAME)
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    monkeypatch.setattr(privacy, "tracked", lambda root: sorted(p for p in root.rglob("*") if p.is_file()))
    return sorted((f.origin, f.name) for f in privacy.scan_paths(tmp_path))


def test_json_jsonl_csv_and_a_suffixless_file_are_scanned(tmp_path, monkeypatch):
    got = _tree(tmp_path, monkeypatch, {
        "a.json": '{"path": "/Users/someone/run"}\n',
        "b.jsonl": '{"t": "fine"}\n{"t": "/home/someone/x"}\n',
        "c.csv": "id,where\n1,/Volumes/Models/hf\n",
        "NOTICE": f"set up by {FAKE_NAME}\n",
    })
    assert got == [("NOTICE", "person-name"), ("a.json", "home-path"), ("b.jsonl", "home-path"),
                   ("c.csv", "named-volume")]


def test_a_binary_file_is_not_read(tmp_path, monkeypatch):
    assert _tree(tmp_path, monkeypatch, {"x.png": b"\x89PNG\r\n\x1a\n\0\0 /Users/someone/x\n"}) == []


def test_a_name_after_an_escaped_newline_is_found():
    """Raw JSON spells the newline `\\n`, so the name would sit in one word with the n before it."""
    extra = ("person-name", re.compile(rf"\b{FAKE_NAME}\b", re.I), "")
    assert [f.name for f in privacy.scan(f'{{"r": "a run by\\n{FAKE_NAME}"}}', "t", extra)] == ["person-name"]
    assert [f.line for f in privacy.scan(f'{{}}\n{{"r": "ok\\t{FAKE_NAME}"}}', "t", extra)] == [2]
    assert privacy.scan(f'{{"r": "a run by\\n{FAKE_NAME}ian"}}', "t", extra) == []


def test_a_public_corpus_is_spared_the_name_pattern_only(tmp_path, monkeypatch):
    spared = next(k for k, v in privacy.SPARED.items() if v == {"person-name"} and k.endswith(".jsonl"))
    got = _tree(tmp_path, monkeypatch, {spared: f'{{"text": "{FAKE_NAME.upper()} SAID"}}\n{{"p": "/Users/someone/x"}}\n'})
    assert got == [(spared, "home-path")]


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/privacy.py:SPARED")
def test_every_spared_file_is_tracked_and_spares_a_real_pattern():
    """A spared path that was renamed away would spare nothing, and a misspelt pattern would spare everything else."""
    root = Path(__file__).resolve().parent.parent
    tracked = {p.relative_to(root).as_posix() for p in privacy.tracked(root)}
    known = {name for name, _, _ in privacy.PATTERNS} | {"person-name"}
    assert set(privacy.SPARED) <= tracked
    assert all(v and v <= known for v in privacy.SPARED.values())


@pytest.mark.parametrize("raw,masked", [
    ("/Users/someone/.cache/x.py", "~/.cache/x.py"),
    ("/home/someone/src", "~/src"),
    ("/tmp/pytest-of-someone/pytest-0/t0", "/tmp/pytest-of-USER/pytest-0/t0"),
    ("~/.claude/projects/-Users-someone-projects/s.jsonl", "~/.claude/projects/-Users-USER-projects/s.jsonl"),
    ("/private/tmp/claude-504/-home-someone-src/x", "/private/tmp/claude-504/-home-USER-src/x"),
    ("/Users/USER/x and pytest-of-USER and -Users-USER-p", "/Users/USER/x and pytest-of-USER and -Users-USER-p"),
    ("/Users/<ACCOUNT_1>/x -Users-<ACCOUNT_1>-p", "/Users/<ACCOUNT_1>/x -Users-<ACCOUNT_1>-p"),
    ("a well-Users-ish word", "a well-Users-ish word"),
])
def test_mask_home_hides_the_account_a_path_spells(raw, masked):
    assert privacy.mask_home(raw) == masked
    assert privacy.mask_home(masked) == masked
