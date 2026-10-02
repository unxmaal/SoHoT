"""The page a person labels on. Issue #286."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest
import yaml

from harness import label_server, rubric_eval as rv

RUBRIC = {
    "name": "durable-fact", "version": 1,
    "instructions": "Does the message state a durable technical fact?",
    "label": "verdict",
    "schema": {"type": "object", "required": ["verdict"],
               "properties": {"verdict": {"enum": ["fact", "no-fact"]}}},
}


@pytest.fixture
def served(tmp_path):
    (tmp_path / "rubric.yaml").write_text(yaml.safe_dump(RUBRIC), encoding="utf-8")
    items = [{"id": "a", "text": "Set J6 to 2-3 <script>x</script>"},
             {"id": "b", "text": "lol same"}]
    (tmp_path / "items.jsonl").write_text(
        "".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    srv = label_server.make(tmp_path, port=0, repeat_rate=0.0, seed=1)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield tmp_path, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url):
    return urllib.request.urlopen(url).read().decode("utf-8")


def _post(url, **form):
    data = urllib.parse.urlencode(form).encode("utf-8")
    try:
        return urllib.request.urlopen(url, data=data).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_the_page_shows_the_item_and_one_button_per_label(served):
    _, url = served
    page = _get(url + "/")
    assert "Set J6 to 2-3" in page
    for value in ("fact", "no-fact", rv.CANT_TELL):
        assert f'value="{value}"' in page
    assert RUBRIC["instructions"] in page


def test_item_text_is_escaped(served):
    _, url = served
    assert "<script>x</script>" not in _get(url + "/")


def test_a_repeat_looks_like_any_other_item(served):
    """A repeat that announces itself measures memory, not judgment."""
    _, url = served
    assert "repeat" not in _get(url + "/").lower()


def test_a_label_is_recorded_and_the_next_item_follows(served):
    root, url = served
    _post(url + "/label", id="a", label="fact")
    assert rv.labels(root) == {"a": ["fact"]}
    assert "lol same" in _get(url + "/")


def test_an_invalid_label_is_refused_and_not_recorded(served):
    root, url = served
    assert _post(url + "/label", id="a", label="maybe") == 400
    assert rv.labels(root) == {}


def test_the_page_says_when_everything_is_labelled(served):
    root, url = served
    _post(url + "/label", id="a", label="fact")
    _post(url + "/label", id="b", label="no-fact")
    assert "Nothing left to label" in _get(url + "/")


def test_a_second_label_for_an_item_is_recorded_as_a_repeat(served):
    """Decided from the store, never from the form."""
    root, url = served
    _post(url + "/label", id="a", label="fact")
    _post(url + "/label", id="a", label="fact")
    rows = [json.loads(x) for x in
            (root / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["repeat"] for r in rows] == [False, True]
