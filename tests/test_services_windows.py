"""Running the services on a machine whose main job is something else.

scripts/launchd.sh installs units with RunAtLoad and KeepAlive, which is right
for a machine that exists to serve. The Windows box is a machine with a day job that also
runs this, so the same behaviour there would hold VRAM and CPU against whatever
is being played, and would do it again after every reboot without being asked.

Most of this is a grep over the scripts, for the reason test_service_pinning
gives: the alternative is registering real scheduled tasks in CI, and the
failure being guarded against is visible in the text.

The `status` probe tests are the exception and run for real, against a fake on
loopback. What they guard is not visible in the text: whether an HTTP status
is read as serving, as alive and keyed, or as wedged. A grep asserting the
word 401 appears somewhere would have passed the version of the code that
printed WEDGED for a healthy node. #757.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

import shells

REPO = Path(__file__).resolve().parents[1]
SERVICES = REPO / "scripts" / "services.sh"
LLAMACPP = REPO / "scripts" / "serve-llamacpp.sh"
APIKEY = REPO / "scripts" / "api-key.sh"

#: Anything that would make Windows start something without being asked. The
#: PowerShell trigger types and the schtasks schedules that fire on their own.
_AUTOSTART = re.compile(
    r"New-ScheduledTaskTrigger|Register-ScheduledTask|"
    r"/sc\s+(ONSTART|ONLOGON|ONIDLE|DAILY|WEEKLY|MINUTE|HOURLY)|"
    r"HKCU.*\\\\Run|shell:startup",
    re.I)

#: The one region allowed to register anything, fenced so the reversal #684
#: asks for is visible in the text rather than spread through the file. The
#: markers are literal because brace matching over shell is guesswork, and a
#: test that guesses wrong here passes while the rule is broken.
_NODE_BEGIN = "# BEGIN node registration"
_NODE_END = "# END node registration"


def _node_region(text):
    """The lines between the node markers, or none when they are absent."""
    lines = text.splitlines()
    begin = next((i for i, line in enumerate(lines) if _NODE_BEGIN in line), None)
    end = next((i for i, line in enumerate(lines) if _NODE_END in line), None)
    if begin is None or end is None or end < begin:
        return []
    return lines[begin:end + 1]


def _outside_node_region(text):
    """Every other line, which the no-autostart rule still governs."""
    lines = text.splitlines()
    region = _node_region(text)
    if not region:
        return lines
    begin = next(i for i, line in enumerate(lines) if _NODE_BEGIN in line)
    return lines[:begin] + lines[begin + len(region):]


def test_the_windows_services_script_exists():
    assert SERVICES.exists(), (
        "the Windows box needs a way to start and stop the services that is "
        "not launchd")


def test_nothing_registers_itself_to_start_on_its_own():
    """THE POINT OF THIS FILE. A machine with a day job that quietly starts a language
    model server at logon has lost 8 GB of VRAM to a machine that was supposed
    to be idle, and the owner finds out from a frame rate rather than a log.

    #684 makes this box a serving node behind the gateway, which does need one
    registered task. That is allowed in the fenced node region and nowhere
    else, so the default verbs keep the behaviour this test was written for:
    a reboot leaves the card empty unless someone asked otherwise.
    """
    text = SERVICES.read_text(encoding="utf-8")
    offenders = [line.strip() for line in _outside_node_region(text)
                 if _AUTOSTART.search(line) and not line.strip().startswith("#")]
    assert not offenders, (
        "services.sh would start something without being asked, outside the "
        "opt-in node region: " + "; ".join(offenders))


def test_stopping_takes_the_whole_process_tree():
    """The launcher is bash and the server is its child. Ending the parent
    leaves llama-server holding the card, which is the state this exists to
    avoid."""
    text = SERVICES.read_text(encoding="utf-8")
    assert re.search(r"taskkill[^\n]*/[Tt]", text), (
        "stop should kill the tree, or the model stays resident in VRAM")


def test_status_reports_what_the_card_is_holding():
    """Whether the services are running is the wrong question before a game.
    The question is whether anything still has VRAM."""
    text = SERVICES.read_text(encoding="utf-8")
    assert "nvidia-smi" in text, (
        "status should say what the card is holding, not only which pids are up")


@pytest.mark.parametrize("verb", ["start", "stop", "status"])
def test_it_offers_the_verbs_a_person_needs(verb):
    text = SERVICES.read_text(encoding="utf-8")
    assert re.search(rf"^\s*{verb}\)", text, re.M), f"no {verb} subcommand"


def test_the_text_server_gives_the_card_back_when_idle():
    """Measured on the 4070: a request takes VRAM from 2462 to 3296 MiB, and
    fifteen seconds later it is 2473 again. Without this a server left running
    holds the model for as long as the process lives, which on this machine
    means until someone notices."""
    text = LLAMACPP.read_text(encoding="utf-8")
    assert "--sleep-idle-seconds" in text
    assert "${LLAMACPP_SLEEP_IDLE:-" in text, (
        "the idle timeout should be overridable on a machine that serves "
        "full time")


def test_windows_tool_flags_are_written_so_msys_does_not_eat_them():
    """A SINGLE-SLASH FLAG IS A PATH TO GIT BASH.

    `taskkill /F /IM x` runs, prints nothing, exits 0 and kills nothing,
    because MSYS rewrites /F into a Windows path before taskkill sees it. The
    double-slash form survives. This cost an hour of believing stop was broken
    when the script was right and the command typed beside it was not, and it
    is invisible in review: both spellings look correct.
    """
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.sh")):
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for tool in ("taskkill", "tasklist", "schtasks", "sc.exe"):
                if tool not in line:
                    continue
                # Followed by whitespace or end of line, so a real path
                # like /c/Users does not read as a mangled flag.
                rest = line.split(tool, 1)[1]
                if re.search(r"(?<![/\w])/[A-Za-z]{1,4}(?=\s|$)", rest):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "single-slash flags are rewritten as paths by MSYS; use // -- "
        + "; ".join(offenders))


def _status_against(handler_code, env, tmp_path):
    """Run `services.sh status` against a fake on loopback, and return stdout.

    harness.loopback, not http.server: a stock server costs about 35 s of
    reverse DNS on the macOS runner and conftest refuses the lookup outright
    (#711).
    """
    import http.server
    import threading

    from harness import loopback

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(handler_code)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = loopback.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        full = dict(os.environ, LLAMACPP_PORT=str(port),
                    LOCALHARNESS_HOME=str(tmp_path), **env)
        done = subprocess.run(
            [shells.resolve("bash"), "scripts/services.sh", "status"],
            cwd=REPO, capture_output=True, text=True, timeout=120, env=full)
        return done.stdout
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_node_that_demands_a_key_is_not_reported_wedged(tmp_path):
    """THE FAILURE THIS GUARDS. A keyed node answers 401 to an
    unauthenticated probe, curl -fsS called that a failure, and status printed

        llamacpp  WEDGED:18082 holds the port and does not answer

    for a node that was serving: /health 200, /v1/models 200 with the key, and
    completions round-tripping. It is the inverse of #255 and misleads the same
    expensive way, because status is what gets read before starting a game.
    #757.
    """
    out = _status_against(401, {}, tmp_path)
    assert "WEDGED" not in out, out
    assert "keyed" in out, out


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_port_held_by_something_that_cannot_answer_is_still_wedged(tmp_path):
    """The #255 guarantee has to survive the fix. A 500 is not an auth
    challenge and must still read as wedged, or this trades one misreport for
    another."""
    out = _status_against(500, {}, tmp_path)
    assert "WEDGED" in out, out


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_the_probe_key_never_reaches_the_command_line(tmp_path):
    """A bearer token in argv is readable by every other process here, which is
    why serve-llamacpp.sh passes --api-key-file rather than --api-key. The
    probe uses curl -K with a config file for the same reason, and removes it
    afterwards."""
    region = SERVICES.read_text(encoding="utf-8")
    assert "-K " in region, "probe with a curl config, not -H"
    offenders = [line.strip() for line in region.splitlines()
                 if "Authorization: Bearer" in line
                 and "printf" not in line
                 and not line.lstrip().startswith("#")]
    assert not offenders, (
        "the token would reach argv: " + "; ".join(offenders))
    key_file = tmp_path / "k.txt"
    key_file.write_text("f" * 64, encoding="utf-8")
    _status_against(200, {"LLAMACPP_API_KEY_FILE": str(key_file)}, tmp_path)
    left = list((tmp_path / "run").glob("probe-auth-*"))
    assert not left, f"probe config left behind: {left}"


def _rotate(tmp_path, script, timeout=60):
    """Run `script` with scripts/logs.sh sourced, in tmp_path."""
    done = subprocess.run(
        [shells.resolve("bash"), "-c",
         f'set -u; cd "{REPO.as_posix()}"; . scripts/logs.sh; '
         f'cd "{tmp_path.as_posix()}"; {script}'],
        cwd=REPO, capture_output=True, text=True, timeout=timeout)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_restart_keeps_the_previous_sessions_log(tmp_path):
    """THE FAILURE THIS GUARDS. Both halves truncate on start, so without
    rotation the session before this one is gone. A 32B load failed
    intermittently on the 4070 and the useful comparison was against an
    earlier run that had succeeded on identical flags; those lines had already
    been destroyed by the restart in between. #786.
    """
    log = tmp_path / "llamacpp.log"
    log.write_text("first session\n", encoding="utf-8")
    _rotate(tmp_path, 'rotate_log llamacpp.log')
    assert not log.exists(), "the live name should be free for the new session"
    assert (tmp_path / "llamacpp.log.1").read_text(encoding="utf-8") == \
        "first session\n"


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_each_restart_shifts_the_older_generations_up(tmp_path):
    log = tmp_path / "s.log"
    for n in ("one", "two", "three"):
        log.write_text(f"{n}\n", encoding="utf-8")
        _rotate(tmp_path, 'rotate_log s.log')
    assert (tmp_path / "s.log.1").read_text(encoding="utf-8") == "three\n"
    assert (tmp_path / "s.log.2").read_text(encoding="utf-8") == "two\n"
    assert (tmp_path / "s.log.3").read_text(encoding="utf-8") == "one\n"


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_retained_history_is_bounded(tmp_path):
    """LOG_KEEP generations and no more, or a box that restarts often fills a
    disk with logs nobody will read."""
    log = tmp_path / "s.log"
    for n in range(6):
        log.write_text(f"session {n}\n", encoding="utf-8")
        _rotate(tmp_path, 'LOG_KEEP=3 rotate_log s.log')
    kept = sorted(p.name for p in tmp_path.glob("s.log*"))
    assert kept == ["s.log.1", "s.log.2", "s.log.3"], kept


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_log_over_the_cap_is_dropped_rather_than_kept(tmp_path):
    """Kept history is for reading. A huge file is grepped once and regretted,
    and it would evict two useful generations to sit there."""
    log = tmp_path / "s.log"
    log.write_text("x" * 5000, encoding="utf-8")
    _rotate(tmp_path, 'LOG_MAX_BYTES=1000 rotate_log s.log')
    assert not log.exists()
    assert not (tmp_path / "s.log.1").exists(), \
        "an oversized log should not take a generation slot"


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_rotating_a_log_that_does_not_exist_is_not_an_error(tmp_path):
    """First ever start. Returning non-zero here would make start_one look
    like it failed under set -e."""
    _rotate(tmp_path, 'rotate_log never-written.log; echo ok')


def test_the_log_is_rotated_before_anything_redirects_into_it():
    """Rotation after the redirect would keep an empty file and throw away the
    session it was supposed to save."""
    text = SERVICES.read_text(encoding="utf-8")
    assert "source scripts/logs.sh" in text, "services.sh should source logs.sh"
    rotate = text.index("rotate_log")
    for flag in ("-RedirectStandardOutput", '>"$LOGS/'):
        assert flag not in text or rotate < text.index(flag), (
            f"{flag} appears before the log is rotated")


def test_the_node_region_is_fenced():
    """The allowance has to name its own boundaries.

    Without both markers _outside_node_region falls back to the whole file,
    and the no-autostart rule would then be enforced over nothing while still
    reporting green. The fence is the thing under test, not a formality.
    """
    text = SERVICES.read_text(encoding="utf-8")
    assert _node_region(text), (
        f"services.sh needs {_NODE_BEGIN!r} and {_NODE_END!r} around the one "
        "region allowed to register a task")


@pytest.mark.parametrize("verb", ["install-node", "uninstall-node"])
def test_registering_the_node_is_a_verb_of_its_own(verb):
    """#684 needs a node that survives a reboot. It does not need one on every
    machine that runs this file, so registration is asked for by name."""
    text = SERVICES.read_text(encoding="utf-8")
    assert re.search(rf"^\s*{re.escape(verb)}\)", text, re.M), (
        f"no {verb} subcommand")


@pytest.mark.parametrize("verb", ["start", "stop", "restart", "status"])
def test_the_everyday_verbs_register_nothing(verb):
    """The reversal is scoped to install-node. If `start` reached the
    registration then every ordinary use would leave a task behind, which is
    the state #110 ruled out and the one this box was found in."""
    text = SERVICES.read_text(encoding="utf-8")
    branch = re.search(rf"^\s*{verb}\)(.*)$", text, re.M)
    assert branch, f"no {verb} subcommand"
    assert "install_node" not in branch.group(1), (
        f"{verb} would register a task")


def test_the_node_task_starts_the_service_through_the_launcher():
    """A task that ran llama-server itself would bypass serve-llamacpp.sh and
    lose --sleep-idle-seconds with it. Giving the card back when idle is what
    makes a registered node tolerable on a machine with a day job, so the task
    goes through the same launcher every other path uses."""
    region = "\n".join(_node_region(SERVICES.read_text(encoding="utf-8")))
    assert "start llamacpp" in region, (
        "the node task should run this script's own start verb")
    assert "llama-server" not in region, (
        "the node task should not invoke the server directly; that skips the "
        "launcher and the idle sleep")


@pytest.mark.parametrize("var", ["LLAMACPP_BIN", "LLAMACPP_MODELS_DIR",
                                 "LLAMACPP_API_KEY_FILE"])
def test_the_launcher_carries_the_environment_the_node_needs(var):
    """A LOGON TASK INHERITS NOTHING FROM THE INSTALLING SHELL.

    The first version exported host, port and the key file only. The node then
    started at logon, resolved the models directory to the default inside the
    checkout because LLAMACPP_MODELS_DIR lived in that shell and nowhere else,
    and exited 1. From a gateway that reads as an unreachable node rather than
    as one that never ran. LLAMACPP_BIN is here for the same reason: a box can
    carry more than one llama.cpp build. #736.
    """
    region = "\n".join(_node_region(SERVICES.read_text(encoding="utf-8")))
    assert var in region, f"the generated launcher should carry {var}"


def test_installing_a_node_demands_a_models_directory():
    """Falling back to $HF_HOME/gguf puts a node's weights path inside the
    checkout, where there are none. Naming it is part of setting up a node, as
    naming the key file already is."""
    region = "\n".join(_node_region(SERVICES.read_text(encoding="utf-8")))
    assert re.search(r'-z "\$\{LLAMACPP_MODELS_DIR:-\}"', region), (
        "install-node should refuse an unset LLAMACPP_MODELS_DIR")


def test_the_key_is_passed_as_a_file_not_as_an_argument():
    """A key in argv is readable by every other process on the box, and it
    lands in the task definition and in any log that echoes the command. The
    server takes --api-key-file for exactly this reason."""
    text = LLAMACPP.read_text(encoding="utf-8")
    assert "--api-key-file" in text, "the launcher should pass the key by file"
    offenders = [line.strip() for line in text.splitlines()
                 if "--api-key" in line
                 and "--api-key-file" not in line
                 and not line.lstrip().startswith("#")]
    assert not offenders, (
        "the key would reach argv: " + "; ".join(offenders))


def test_the_key_flag_survives_bash_3_2_when_no_key_is_set():
    """macOS ships bash 3.2 as /bin/bash, and there an EMPTY array expanded as
    "${arr[@]}" counts as unbound under set -u.

    The plain spelling aborted the launcher with 'KEY_ARGS[@]: unbound
    variable' on every machine that sets no key, which is most of them. It
    passed under bash 5 locally and the macOS runner caught it. CTX_ARGS never
    showed this because it always has at least one element.
    """
    text = LLAMACPP.read_text(encoding="utf-8")
    assert 'KEY_ARGS[@]+"${KEY_ARGS[@]}"' in text, (
        "expand the key array with the +alternate form, or bash 3.2 aborts "
        "whenever no key is set")
    offenders = [line.strip() for line in text.splitlines()
                 if '"${KEY_ARGS[@]}"' in line
                 and "KEY_ARGS[@]+" not in line
                 and not line.lstrip().startswith("#")]
    assert not offenders, (
        "unguarded empty-array expansion: " + "; ".join(offenders))


def test_a_keyless_launcher_passes_no_key_flag():
    """Most machines run this with no key at all. An empty --api-key-file
    would be a flag pointing at nothing, which the server rejects at startup,
    so the flag has to be absent rather than empty."""
    text = LLAMACPP.read_text(encoding="utf-8")
    assert "LLAMACPP_API_KEY_FILE" in text
    assert re.search(r"KEY_ARGS|key_args", text), (
        "the key flag should be built conditionally, not passed always")


def test_the_node_reports_what_is_missing_rather_than_listing_steps():
    """The firewall rule and the never-sleep setting need admin and nothing
    here owns them, so they used to be printed every time and the reader had
    to guess whether they had already been run. Both can be READ without
    admin, so both are read."""
    region = "\n".join(_node_region(SERVICES.read_text(encoding="utf-8")))
    assert "Get-NetFirewallRule" in region, (
        "check the firewall rather than telling the reader to check it")
    assert "powercfg /query" in region, (
        "read the current AC standby index rather than always printing the set "
        "command")
    assert re.search(r"^\s*check-node\)", SERVICES.read_text(encoding="utf-8"),
                     re.M), "no check-node subcommand"


def test_installing_the_node_checks_itself():
    """install-node that registered a task and said nothing about the two
    steps it cannot perform is how this node ended up reachable by accident
    and asleep by default."""
    region = "\n".join(_node_region(SERVICES.read_text(encoding="utf-8")))
    body = region.split("install_node()", 1)[-1].split("node_firewall_ok()", 1)[0]
    assert "check_node" in body, (
        "install-node should finish by reporting what is still missing")


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_bom_prefixed_key_file_yields_the_bare_key(tmp_path):
    """PowerShell 5.1 writes a UTF-8 BOM for -Encoding utf8.

    The BOM went into the key the server expected and was stripped from the
    Authorization header on the way in, so the CORRECT key returned 401 and
    read as a key mismatch. It cost a while to find because both sides looked
    identical in every log. 67 bytes where 64 were meant.
    """
    key = "0123456789abcdef" * 4
    path = tmp_path / "api-key.txt"
    path.write_bytes(b"\xef\xbb\xbf" + key.encode("ascii") + b"\r\n")
    done = subprocess.run(
        [shells.resolve("bash"), "-c",
         f'. scripts/api-key.sh; read_api_key "{path.as_posix()}"'],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == key
    assert len(done.stdout.strip()) == 64


@pytest.mark.skipif(shells.resolve("bash") is None,
                    reason="no bash on this machine")
def test_a_missing_key_file_is_an_error_not_an_empty_key():
    """An unreadable key file silently yielding "" would start the server wide
    open on a LAN address, which is worse than not starting at all."""
    done = subprocess.run(
        [shells.resolve("bash"), "-c",
         '. scripts/api-key.sh; read_api_key /nonexistent/key.txt'],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    assert done.returncode != 0, "a missing key file should fail loudly"
