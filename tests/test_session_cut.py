"""A session cut at the first edit of a fix's file: what is kept, where it stops, and the leak check. #1095."""
import pytest

from evals import session_cut as sc

E = sc.Event
FILES = ["harness/widget.py"]


def test_an_edit_tool_on_a_fix_file_is_an_edit_and_one_elsewhere_is_not():
    assert sc.edits(E(1, "call", "Edit", input={"file_path": "/w/sohot-9/harness/widget.py"}), FILES)
    assert sc.edits(E(1, "call", "Write", input={"file_path": "harness/widget.py"}), FILES)
    assert not sc.edits(E(1, "call", "Edit", input={"file_path": "/w/harness/widget_test.py"}), FILES)
    assert not sc.edits(E(1, "call", "Read", input={"file_path": "/w/harness/widget.py"}), FILES)


def test_a_shell_command_that_writes_a_fix_file_is_an_edit_and_one_that_reads_it_is_not():
    for cmd in ("sed -i '' 's/a/b/' harness/widget.py", "cd harness && sed -i 's/x/y/' widget.py",
                "python3 - <<'EOF'\nPath('harness/widget.py').write_text(s)\nEOF", "cat > harness/widget.py <<EOF"):
        assert sc.edits(E(1, "call", "Bash", input={"command": cmd}), FILES), cmd
    for cmd in ("cat harness/widget.py", "grep -n def harness/widget.py", "sed -n 1,40p harness/widget.py",
                "sed -i 's/a/b/' harness/other.py"):
        assert not sc.edits(E(1, "call", "Bash", input={"command": cmd}), FILES), cmd


def test_the_cut_stops_before_the_first_edit_after_the_anchor():
    evs = [E(1, "call", "Edit", input={"file_path": "harness/widget.py"}), E(5, "user", body="go"),
           E(6, "call", "Read", input={"file_path": "harness/widget.py"}), E(6, "result", "Read", "x"),
           E(7, "call", "Edit", input={"file_path": "harness/widget.py"})]
    assert sc.first_edit(evs, FILES, after=5) == 4
    assert sc.first_edit(evs, ["harness/none.py"]) is None


def test_reads_keep_their_output_up_to_the_cap_and_other_large_outputs_lose_the_body():
    big = "line\n" * 2000
    evs = [E(1, "user", body="fix the widget"),
           E(2, "call", "Read", input={"file_path": "harness/widget.py"}), E(2, "result", "Read", big),
           E(3, "call", "Bash", input={"command": "make check"}), E(3, "result", "Bash", big),
           E(4, "call", "mcp__kb__search", input={"query": "widget"}), E(4, "result", "mcp__kb__search", "private")]
    out = sc.render(evs, budget=100_000, cap=300)
    assert "## tool Read harness/widget.py\nline\n" in out and "more bytes]" in out
    assert "$ make check\n[10000 bytes of output not shown]" in out
    assert "private" not in out and "[7 bytes of output not shown]" in out


@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="evals/session_cut.py:render(budget)")
def test_the_budget_keeps_the_opening_turn_and_the_latest_entries():
    evs = [E(0, "user", body="the request")] + [E(i, "text", body=f"step {i} " + "x" * 80) for i in range(1, 50)]
    out = sc.render(evs, budget=1000, cap=300)
    assert out.startswith("## user\nthe request") and "step 49" in out and "step 1 " not in out
    assert "earlier entries not shown" in out and len(out.encode("utf-8")) < 1200


def test_system_reminders_never_reach_the_cut():
    recs = [{"type": "user", "timestamp": "2026-10-22T00:00:00Z",
             "message": {"content": "do it <system-reminder>secret context</system-reminder>"}}]
    (e,) = sc.events(recs, lambda r: r["message"]["content"], lambda t: 1.0)
    assert e.body == "do it"


def test_added_lines_are_new_long_source_lines_and_a_cut_holding_one_leaks():
    diff = ("+++ b/harness/widget.py\n+    return compute_total(items, tax=True)\n+    x = 1\n"
            "+    already_there_at_base_line()\n")
    lines = sc.added_lines(diff, {"harness/widget.py": "def f():\n    already_there_at_base_line()\n"})
    assert lines == ["return compute_total(items, tax=True)"]
    assert sc.leaks("the agent wrote: return compute_total(items, tax=True)", lines) == lines
    assert sc.leaks("nothing of the fix here", lines) == []


def test_a_command_output_over_the_command_cap_loses_its_body_even_under_the_read_cap():
    evs = [E(1, "user", body="go"), E(2, "call", "Bash", input={"command": "uv run infovore claims"}),
           E(2, "result", "Bash", "someone said a thing " * 30)]
    out = sc.render(evs, budget=100_000, cap=1500)
    assert "someone said" not in out and "bytes of output not shown" in out


def test_a_truncated_read_ends_on_a_word_boundary():
    out = sc.render([E(1, "user", body="go"), E(2, "call", "Read", input={"file_path": "a.py"}),
                     E(2, "result", "Read", "alpha beta gamma delta " * 40)], cap=50)
    assert "a.py\nalpha beta gamma delta alpha beta gamma delta\n[... " in out
