"""The MCP surface: the same `lh` a local agent runs, reachable from the LAN.

A second operator gets svg, web, code and image from their own Claude Code on
their own machine. Everything here shells out to `lh` rather than reimplementing it,
because the repo's rule is that every caller runs identical commands -- the CLI
and the eval suite already do, and a third caller that drifted would expose a
product nobody ships.

These tests never generate anything. They assert the command built, the shape
of what comes back, and that the expensive lane goes through the queue.
"""
import pytest

mcp_server = pytest.importorskip(
    "harness.mcp_server",
    reason="needs the `mcp` group: uv run --group mcp pytest")


@pytest.fixture
def spy(monkeypatch, tmp_path):
    """Capture the argv, and fake `lh` writing its artifact."""
    calls = []

    def fake_lh(argv, timeout=None):
        """What `lh` ACTUALLY does, which is not what I first assumed.

        `lh svg` and `lh web` always write a file and print its PATH; only
        `lh code` prints content to stdout. The first version of this fake
        returned markup on stdout, which is what I believed rather than what
        the CLI does, so the tests passed while the tool handed callers a path
        string where an SVG document should have been. Caught live over the
        LAN, not here."""
        calls.append(argv)
        assert "-o" in argv, "every verb should be given an explicit -o"
        out = argv[argv.index("-o") + 1]
        body = (b"\x89PNG\r\n\x1a\n" + b"x" * 200
                if argv[len(mcp_server.LH)] == "image"
                else b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        open(out, "wb").write(body)
        return out

    monkeypatch.setattr(mcp_server, "run_lh", fake_lh)
    monkeypatch.setattr(mcp_server, "OUTDIR", tmp_path)
    return calls


def test_svg_returns_the_markup_not_the_path_it_was_written_to(spy):
    """`lh svg` prints where it put the file. A caller on another machine
    cannot open that path, and an agent asking for an SVG wants the document."""
    out = mcp_server.svg("two concentric gears")
    assert out.startswith("<svg"), out
    assert spy[0][:len(mcp_server.LH) + 1] == [*mcp_server.LH, "svg"]
    assert "two concentric gears" in spy[0]


def test_the_artifact_is_kept_on_the_serving_machine_too(spy, tmp_path):
    """Returned by value AND left on disk: the text is what the caller wanted,
    the file is what makes a bad result inspectable afterwards."""
    mcp_server.svg("a gear")
    written = list(tmp_path.glob("svg-*.svg"))
    assert written and written[0].read_text(encoding="utf-8").startswith("<svg")


def test_web_and_code_are_the_same_shape(spy):
    mcp_server.web("a landing page for a coffee roaster")
    mcp_server.code("a python function that parses an ISO timestamp")
    n = len(mcp_server.LH)
    assert spy[0][n] == "web" and spy[1][n] == "code"


def test_the_model_can_be_chosen_per_call(spy):
    mcp_server.svg("a gear", model="local-large")
    assert "-m" in spy[0] and "local-large" in spy[0]


def run_queue(fail=False):
    """The worker, with `lh` faked: write the artifact the job names."""
    from harness import workqueue as wq

    def popen(argv, cwd=None, stdout=None, stderr=None):
        if fail:
            stdout.write("mflux exited 3: out of memory\n")
            return type("R", (), {"returncode": 3})()
        out = argv[argv.index("-o") + 1]
        body = (b"\x89PNG\r\n\x1a\n" + b"x" * 200 if out.endswith(".png")
                else b"\x00\x00\x00\x18ftypmp42" + b"v" * 200)
        open(out, "wb").write(body)
        return type("R", (), {"returncode": 0})()
    return wq.run_pending(popen=popen)


def test_image_returns_a_job_id_and_runs_nothing(spy):
    """A caller on another machine gets an id at once; the work waits its turn."""
    out = mcp_server.image("a red fox in snow")
    assert out.state == "queued" and out.job
    assert spy == []


def test_a_queued_image_finishes_and_carries_the_file(spy):
    job = mcp_server.image("a red fox in snow", width=64, height=64)
    run_queue()
    status = mcp_server.job_status(job.job)
    assert status.state == "done" and status.path.endswith(".png")


def test_the_image_job_runs_lh_image_with_the_callers_size(spy):
    from harness import workqueue as wq
    job = mcp_server.image("a fox", width=64, height=64)
    argv = wq.get(job.job)["argv"]
    assert argv[:len(mcp_server.LH) + 1] == [*mcp_server.LH, "image"]
    assert argv[argv.index("--width") + 1] == "64"


def test_video_is_queued_the_same_way(spy):
    from harness import workqueue as wq
    job = mcp_server.video("a fox running", frames=22)
    argv = wq.get(job.job)["argv"]
    assert argv[:len(mcp_server.LH) + 1] == [*mcp_server.LH, "video"]
    assert job.kind == "video" and job.state == "queued"


def test_a_queued_job_says_what_it_waits_for(spy):
    from harness import workqueue as wq
    wq.pause()
    job = mcp_server.image("a fox")
    assert "paused" in mcp_server.job_status(job.job).waiting_for


def test_jobs_survive_a_server_restart(spy):
    """The old queue lived in memory; a redeploy lost every waiting job."""
    import importlib
    job = mcp_server.image("a fox")
    importlib.reload(mcp_server)
    assert mcp_server.job_status(job.job).state == "queued"


def test_an_unknown_job_says_so_rather_than_raising(spy):
    assert mcp_server.job_status("nope").state == "unknown"


def test_a_failed_generation_is_reported_not_raised(spy):
    job = mcp_server.image("a fox")
    run_queue(fail=True)
    status = mcp_server.job_status(job.job)
    assert status.state == "failed" and "exited 3" in status.error


def test_job_result_hands_back_the_image_itself(spy):
    """A path on this machine is useless to an agent upstairs."""
    job = mcp_server.image("a fox")
    run_queue()
    import base64
    got = mcp_server.job_result(job.job)
    img = [c for c in got if type(c).__name__ == "Image"][0].to_image_content()
    assert img.mime_type == "image/png"
    assert base64.b64decode(img.data)[:4] == b"\x89PNG"


def test_job_result_hands_back_a_video_as_an_embedded_file(spy):
    import base64
    job = mcp_server.video("a fox running")
    run_queue()
    got = mcp_server.job_result(job.job)
    res = [c for c in got if getattr(c, "type", "") == "resource"][0].resource
    assert res.mime_type == "video/mp4"
    assert base64.b64decode(res.blob)[4:8] == b"ftyp"


def test_job_result_before_the_job_is_done_says_so(spy):
    job = mcp_server.image("a fox")
    got = mcp_server.job_result(job.job)
    assert "queued" in got[0].text


def test_every_tool_is_registered_on_the_server():
    names = {t.name for t in mcp_server.SERVER._tool_manager.list_tools()}
    assert {"svg", "web", "code", "image", "video", "job_status",
            "job_result"} <= names


def test_speech_is_not_exposed():
    """Speaking over the LAN was ruled out."""
    names = {t.name for t in mcp_server.SERVER._tool_manager.list_tools()}
    assert "say" not in names


# ---- reachable from the LAN, and only from it ------------------------------

def test_the_lan_hostname_is_allowed_or_the_other_machine_gets_a_rejection():
    """MCP 2.x turns DNS-rebinding protection ON by default with an EMPTY
    allowlist, so a request carrying this host's own `.local` name is refused
    before it reaches a tool. Binding 0.0.0.0 is not enough on its own."""
    s = mcp_server.transport_security(host="0.0.0.0", port=8899)
    assert s.enable_dns_rebinding_protection
    joined = " ".join(s.allowed_hosts)
    assert ".local:8899" in joined
    assert "127.0.0.1:8899" in joined


def test_protection_stays_on_because_the_lan_rule_does_not_cover_it():
    """No LAN auth is a decision about who can reach the port. DNS rebinding
    does not need the port to be reachable: it needs someone on the LAN to
    open a web page. Different threat, so it keeps its guard."""
    assert mcp_server.transport_security("0.0.0.0", 8899).enable_dns_rebinding_protection


def test_an_extra_host_can_be_allowed():
    # privacy-ok: a fabricated name, which is the point of the test
    s = mcp_server.transport_security("0.0.0.0", 8899, extra=["other-host.local"])
    # privacy-ok: same fabricated name
    assert any("other-host.local:8899" == h for h in s.allowed_hosts)


def test_a_job_comes_back_as_fields_not_json_in_a_string():
    """The consumer is an agent. Without a declared return type the SDK sends
    the dict as a JSON blob inside a text block and structured_content is None,
    so the caller has to parse a string to find out whether the job finished."""
    tools = {t.name: t for t in mcp_server.SERVER._tool_manager.list_tools()}
    for name in ("image", "video", "job_status"):
        schema = tools[name].output_schema
        assert schema, f"{name} declares no output schema"
        assert "job" in schema["properties"] and "state" in schema["properties"]


def test_lh_is_this_interpreter_and_never_a_path_lookup():
    """`lh` on PATH is an editable install of whatever checkout ran
    `uv tool install`, so the deployed server would run branch code. #290."""
    import sys
    assert mcp_server.LH == [sys.executable, "-m", "harness.cli"]
