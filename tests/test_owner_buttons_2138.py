"""Buttons for deploy pause/resume, review on/off, router relist and the store's daily dump: rendered, pressed, confirmed, and the state
read back from a scratch home. Real: the soh verbs for deploy and review, each as its own process. Faked: for relist, the router restart and
its GET /models; for the dump, pg_dump and pg_restore -l in the container; those two verbs run in this process. #2138."""
from __future__ import annotations

import contextlib
import io
import re

import pytest

from harness import deploy, features, gguf, review, router, store, store_service as svc
from harness import owner_actions as oa
from harness import status_page as sp
from tests.test_status_buttons_2135 import HOST, NOW, UNITS, audit_lines, gather as base_gather

WHO = {"name": "p", "id": "p"}


def rows_features(conn, now, q):
    return {"rows": [*UNITS, *features.owner_rows()]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")
    from starlette.testclient import TestClient
    import tests.test_status_buttons_2135 as base
    monkeypatch.setattr(base, "rows_features", rows_features)
    monkeypatch.setattr(sp, "cached", lambda: base_gather(tmp_path))
    app = srv.SERVER.streamable_http_app(transport_security=srv.transport_security("0.0.0.0", 8899), host="0.0.0.0")
    return TestClient(app)


@pytest.fixture
def in_process(monkeypatch):
    """The relist and dump verbs run here, so their one faked edge each can be patched."""
    from harness import cli

    def run(argv, run=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = cli.main(list(argv))
        return {"rc": rc, "out": out.getvalue()}
    monkeypatch.setattr(oa, "run_verb", run)


def live(html, action):
    """The forms for `action` whose button is not disabled."""
    return [dict(re.findall(r"name='(\w+)' value='([^']*)'", f)) for f in re.findall(r"<form.*?</form>", html, re.S)
            if f"name='action' value='{action}'" in f and "<button disabled" not in f]


def in_row(html, pattern):
    """The actions of the forms inside the first block `pattern` matches."""
    block = re.search(pattern, html, re.S)
    return re.findall(r"name='action' value='(\w+)'", block.group(0)) if block else []


def switch(html, name):
    return in_row(html, rf"<span class='fn'>{name}</span>.*?</div>")


def band(html):
    return in_row(html, r"<section class='needs'.*?</section>")


def tap(client, action, arg=""):
    """The two presses of POST /status/action on the first form of `action`, as served."""
    form = next(f for f in live(page(client), action) if f.get("arg", "") == arg)
    first = client.post("/status/action", data=form, headers=HOST)
    assert first.status_code == 200 and "Confirm" in first.text, first.text
    nonce = re.search(r"name='confirm' value='([^']+)'", first.text).group(1)
    done = client.post("/status/action", data={**form, "confirm": nonce}, headers=HOST)
    assert done.status_code == 200 and "Done" in done.text, done.text


def page(client):
    return client.get("/status", headers=HOST).text


def refused(tmp_path, action, arg):
    code, text = oa.press("p", {}, {"token": oa.token("p", WHO, NOW), "action": action, "arg": arg}, base_gather(tmp_path), now=NOW,
                          home=tmp_path, run=lambda *a, **k: pytest.fail(f"a forged {action} {arg!r} ran"))
    assert code == 400 and ("does not offer" in text or "not one of the listed" in text), (action, arg, code)


def test_deploys_are_paused_from_the_switch_row_and_resumed_from_the_needs_you_band(tmp_path, client):
    assert not deploy.paused() and switch(page(client), "deploys") == ["deploy_pause"]
    tap(client, "deploy_pause")
    assert deploy.paused()
    shown = page(client)
    assert switch(shown, "deploys") == ["deploy_resume"] and "Deploys are paused" in shown
    assert band(shown) == ["deploy_resume"]
    tap(client, "deploy_resume")
    assert not deploy.paused() and "Deploys are paused" not in page(client)
    assert [x["action"] for x in audit_lines(tmp_path) if x["press"] == "confirm"] == ["deploy_pause", "deploy_resume"]


def test_the_review_is_switched_off_and_on_from_its_row(tmp_path, client):
    assert not review.is_off() and switch(page(client), "review") == ["review_off"]
    tap(client, "review_off")
    assert review.is_off() and switch(page(client), "review") == ["review_on"]
    tap(client, "review_on")
    assert not review.is_off() and switch(page(client), "review") == ["review_off"]


def test_the_router_is_relisted_once_for_what_the_page_says_is_stale(tmp_path, client, monkeypatch, in_process):
    restarts = []
    monkeypatch.setattr(gguf, "refresh_router", lambda expect=(), **kw: restarts.append(tuple(expect)) or "")
    monkeypatch.setattr(router, "phantoms", lambda get=None: {})
    assert "model list is stale" not in page(client) and band(page(client)) == []
    gguf.note_removed(["ghost-model"])
    assert "model list is stale" in page(client) and band(page(client)) == ["router_relist"]
    tap(client, "router_relist")
    assert restarts == [()] and gguf.pending() == [] and "model list is stale" not in page(client)


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/status_page.py:store:chooser")
@pytest.mark.sqlite_store
def test_the_store_dumps_once_a_day_and_the_button_goes_with_the_dump(tmp_path, client, monkeypatch, in_process):
    made = []

    def dump(dest, *, run=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(svc.DUMP_MAGIC + b"fake")
        made.append(dest)
        return dest
    monkeypatch.setattr(svc, "dump", dump)
    monkeypatch.setattr(svc, "verify", lambda p, **kw: None)
    store_row = r"data-rows='store'>.*?</div></div>"
    assert in_row(page(client), store_row) == []
    was = sp.store
    monkeypatch.setattr(sp, "store", lambda conn, why="", home=None: {**was(conn, why, None), "backend": store.POSTGRES})
    assert in_row(page(client), store_row) == ["pg_backup"]
    tap(client, "pg_backup")
    assert len(made) == 1 and svc.backups() == made
    assert in_row(page(client), store_row) == []
    tap(client, "pg_backup")
    assert len(made) == 1, "a second press the same day must not dump or rotate again"


def test_a_forged_choice_for_any_of_them_is_refused_and_nothing_runs(tmp_path, client):
    for action in ("deploy_pause", "deploy_resume", "review_on", "review_off", "router_relist", "pg_backup"):
        for arg in ("x", "--replace", "0", "deploys", "--keep-backups", "1"):
            refused(tmp_path, action, arg)
    refused(tmp_path, "deploy_poll", "")
    refused(tmp_path, "deploy_repair", "12")
    assert not deploy.paused() and not review.is_off()


def test_a_device_that_may_not_press_sees_none_of_the_new_buttons(tmp_path, client):
    shown = client.get("/status", headers={**HOST, "x-forwarded-for": "1.2.3.4"}).text
    assert "name='action'" not in shown
