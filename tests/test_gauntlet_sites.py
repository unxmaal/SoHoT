"""Specific tests a gauntlet detector asked for: each binds one class to one site (#492 B)."""

import configparser
import re
from pathlib import Path

import pytest

from harness import context, disk, inspect, lanes, machine, publish, verify, winners
from harness.memory_store import schema

REPO = Path(__file__).resolve().parent.parent

CLOSED = "a-closed-table-fronting-an-open-set"
SEAM = "each-half-verified-against-its-own-spec-the-seam-against-nothing"


def _ini(path):
    cp = configparser.ConfigParser()
    cp.read_string("[top]\n" + Path(path).read_text(encoding="utf-8"))
    return cp


def test_disk_waits_on_exactly_the_outcomes_the_schema_calls_waypoints():
    # #520: a second copy drifts the day a waypoint is added.
    assert disk.WAITING is schema.WAYPOINTS


@pytest.mark.gauntlet(SEAM, site="env:LLAMACPP_CACHE_TYPE")
def test_the_preset_tells_the_server_the_cache_type_the_plan_assumed(monkeypatch, tmp_path):
    # #521: the plan priced q8_0 KV and the server, told nothing, allocated f16.
    monkeypatch.setenv("LLAMACPP_CACHE_TYPE", "q8_0")
    out = tmp_path / "preset.ini"
    assert context.main([str(out)]) == 0
    star = _ini(out)["*"]
    assert star["cache-type-k"] == "q8_0" and star["cache-type-v"] == "q8_0"


@pytest.mark.gauntlet(SEAM, site="env:LLAMACPP_PARALLEL")
def test_the_slots_the_plan_divided_by_are_the_slots_the_server_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMACPP_PARALLEL", "3")
    out = tmp_path / "preset.ini"
    assert context.main([str(out)]) == 0
    assert _ini(out)["*"]["parallel"] == "3"


@pytest.mark.gauntlet(SEAM, site="env:LLAMACPP_CTX")
def test_the_fallback_context_is_the_one_the_script_falls_back_to(monkeypatch, tmp_path):
    text = (REPO / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")
    script = set(re.findall(r"\$\{LLAMACPP_CTX:-(\d+)\}", text))
    monkeypatch.delenv("LLAMACPP_CTX", raising=False)
    out = tmp_path / "preset.ini"
    assert context.main([str(out)]) == 0
    assert script == {_ini(out)["*"]["c"]}


def _script_default(name, var):
    text = (REPO / "scripts" / name).read_text(encoding="utf-8")
    return re.search(r"\$\{" + var + r":-([^}]+)\}", text).group(1)


def _server_default(var):
    text = (REPO / "harness" / "audio_server.py").read_text(encoding="utf-8")
    return re.search(r"os\.environ\.get\(\"" + var + r"\", \"([^\"]+)\"\)", text).group(1)


@pytest.mark.gauntlet(SEAM, site="env:AUDIO_PORT")
def test_the_audio_server_listens_where_its_launcher_and_its_clients_say():
    port = _server_default("AUDIO_PORT")
    assert port == _script_default("serve-audio-cuda.sh", "AUDIO_PORT")
    from harness import audio
    assert audio.DEFAULT_BASE_URL.split("//", 1)[1].split("/")[0].endswith(f":{port}")


@pytest.mark.gauntlet(SEAM, site="env:AUDIO_HOST")
def test_the_audio_server_binds_the_address_its_launcher_documents():
    assert _server_default("AUDIO_HOST") == _script_default("serve-audio-cuda.sh", "AUDIO_HOST")


@pytest.mark.gauntlet(CLOSED, site="harness/verify.py:COST_S")
def test_every_lane_has_a_cost_rather_than_the_fallback():
    # A new lane would be scheduled at the fallback cost whatever it really costs.
    assert set(lanes.ALL) <= set(verify.COST_S), sorted(set(lanes.ALL) - set(verify.COST_S))


@pytest.mark.gauntlet(CLOSED, site="harness/winners.py:FAMILIES")
def test_every_lane_names_its_family_rather_than_falling_to_alias():
    assert set(lanes.ALL) <= set(winners.FAMILIES), sorted(set(lanes.ALL) - set(winners.FAMILIES))


@pytest.mark.gauntlet(CLOSED, site="harness/publish.py:MAC_MODELS")
def test_an_unlisted_mac_is_named_by_its_identifier_not_another_model():
    got = publish.machine_label({"hw_model": "Mac99,1", "os": "macOS-27", "memory_gb": 64})
    assert got.startswith("Mac99,1")
    assert not any(name in got for name in publish.MAC_MODELS.values())


@pytest.mark.gauntlet(CLOSED, site="harness/machine.py:_OS_FAMILY")
def test_an_unlisted_platform_keeps_its_own_name():
    assert machine.os_family("FreeBSD-14.1-RELEASE-amd64") == "FreeBSD"
    assert machine.os_family("Linux-6.8-x86_64") == "Linux"


@pytest.mark.gauntlet(CLOSED, site="harness/inspect.py:PIPELINE_LANES")
def test_an_unlisted_task_has_no_lane_rather_than_a_guessed_one():
    assert inspect.card_lane("voice-activity-detection") == ""
    assert inspect.card_lane("audio-classification") == ""


@pytest.mark.gauntlet(CLOSED, site="harness/completion.py:ROOT_TAGS")
def test_every_text_lane_unwraps_its_artifact_or_is_named_as_taking_the_reply_whole():
    from evals import core
    from harness import completion
    assert set(completion.ROOT_TAGS) <= core.TEXT_MODALITIES
    assert core.TEXT_MODALITIES - set(completion.ROOT_TAGS) == {"extract", "decide", "claims"}
    assert completion.artifact(' {"a": 1}\n', "extract") == '{"a": 1}'


@pytest.mark.gauntlet(CLOSED, site="harness/inspect.py:TAG_LANES")
@pytest.mark.gauntlet(CLOSED, site="harness/inspect.py:AUDIO_TAGS")
@pytest.mark.gauntlet(CLOSED, site="harness/inspect.py:AUDIO_WORDS")
def test_a_card_tag_no_table_names_files_nowhere_and_every_named_lane_is_real():
    for table in (inspect.TAG_LANES, inspect.AUDIO_TAGS, inspect.AUDIO_WORDS):
        assert set(table.values()) <= set(lanes.ALL), table
    assert inspect.lane_for({"pipeline_tag": "", "tags": ["sound-effects"]}) == ""
    assert inspect.lane_for({"pipeline_tag": "text-to-audio", "tags": ["sound-effects"], "id": "a/b"}) == ""


@pytest.mark.gauntlet(CLOSED, site="harness/runner_gaps.py:VENV_SCRIPTS")
@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_every_runner_venv_has_a_deploy_step_that_installs_into_it(monkeypatch, platform):
    import sys
    from harness import runner_gaps as rg
    monkeypatch.setattr(sys, "platform", platform)
    for venv in sorted({*rg.RUNNER_VENVS.values(), *rg._VENV_ENV, rg.AUDIO_ENV}):
        assert rg.installs(venv, REPO), venv
    assert rg.installs("no-such-venv", REPO) == frozenset()
