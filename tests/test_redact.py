"""Redaction of a request before it becomes a case: every class planted, caught and replaced. #1095."""
import random
import string

import pytest

from evals import redact

R = random.Random(1095)
KNOWN = redact.Known(accounts=("zorblat",), names=("Quentavious",), hosts=("frobnitz-box",))


def _rand(n, alphabet=string.ascii_letters + string.digits):
    while True:
        s = "".join(R.choice(alphabet) for _ in range(n))
        if any(c.isupper() for c in s) and any(c.islower() for c in s) and sum(c.isdigit() for c in s) >= 3:
            return s


#: (class, canary, placeholder prefix): built at run time so no key-shaped literal sits in the tree.
CANARIES = [
    ("secret", "sk-" + "ant-" + "api03-" + _rand(40), "<SECRET_"),
    ("secret", "sk-" + _rand(32), "<SECRET_"),
    ("secret", "gh" + "p_" + _rand(36), "<SECRET_"),
    ("secret", "github_" + "pat_" + _rand(40), "<SECRET_"),
    ("secret", "AK" + "IA" + "".join(R.choice(string.ascii_uppercase + string.digits) for _ in range(16)), "<SECRET_"),
    ("secret", "xox" + "b-" + _rand(24), "<SECRET_"),
    ("secret", "AI" + "za" + _rand(35), "<SECRET_"),
    ("secret", "hf" + "_" + _rand(34), "<SECRET_"),
    ("secret", "eyJ" + _rand(20) + "." + _rand(30) + "." + _rand(20), "<SECRET_"),
    ("secret", _rand(40), "<SECRET_"),
    ("secret", "".join(R.choice("0123456789abcdef") for _ in range(64)), "<SECRET_"),
    ("secret", "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n" + _rand(60) + "\n-----END OPENSSH PRIVATE KEY-----",
     "<SECRET_"),
    ("session", "session_01" + _rand(22), "<SESSION_"),
    ("session", "https://claude.ai/code/session_01" + _rand(22), "<SESSION_"),
    ("request", "req_011C" + _rand(20), "<REQUEST_"),
    ("secret", "/srv/keys/" + _rand(30) + "/x", "<SECRET_"),
    ("id", str(__import__("uuid").UUID(int=R.getrandbits(128))), "<ID_"),
    ("id", "toolu_01" + _rand(20), "<ID_"),
    ("id", "112233445566778899", "<ID_"),
    ("email", "someone.else@example.org", "<EMAIL_"),
    ("path", "/" + "Users/zorblat/projects/x", "<PATH_HOME>"),
    ("path", "/" + "home/zorblat/.config", "<PATH_HOME>"),
    ("path", "/" + "Volumes/Models/hf", "<VOLUME_"),
    ("path", "/private/var/folders/f8/q_d69/T/x", "<PATH_TMP>"),
    ("host", "kitchen-mac" + ".local", "<HOST_"),
    ("host", "frobnitz-box", "<HOST_"),
    ("ip", ".".join(["192", "168", "77", "5"]), "<IP_"),
    ("ip", "fe80::1c2b:3a4d", "<IP_"),
    ("ip", "a4:83:e7:12:34:56", "<IP_"),
    ("handle", "<@123456789012>", "<HANDLE_"),
    ("handle", "member-a1b2", "<HANDLE_"),
    ("account", "zorblat", "<ACCOUNT_"),
    ("account", "-Users-zorblat-projects", "<ACCOUNT_"),
    ("path", "/private/tmp/claude-504/-x/scratchpad", "<PATH_TMP>"),
    ("tz", "Wed Oct 21 17:53:43 EDT 2026", "<TZ_"),
    ("tz", "Date:   Wed Oct 21 17:53:43 2026 -0400", "<TZ_"),
    ("tz", "2026-10-21T17:53:43-04:00", "<TZ_"),
    ("name", "Quentavious", "<NAME_"),
]
CHATS = [
    "[3] someone: the build broke again after the update",
    "[10:41 PM] someone: try clearing the cache first",
    "someone — Today at 10:41 PM\nhave you tried a different cable\nworked for me",
]


@pytest.mark.parametrize("cls,canary,placeholder", CANARIES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CANARIES)])
def test_each_planted_canary_is_caught_and_replaced(cls, canary, placeholder):
    text = f"Please fix this. It printed {canary} and then stopped.\n"
    got = redact.redact(text, KNOWN)
    assert canary not in got.text
    assert placeholder in got.text
    assert got.counts.get(cls, 0) >= 1, got.counts
    assert got.text.startswith("Please fix this. It printed ") and got.text.endswith(" and then stopped.\n")
    assert redact.detect(got.text, KNOWN) == {}
    assert redact.detect(text, KNOWN).get(cls)


@pytest.mark.parametrize("chat", CHATS)
def test_pasted_chat_is_replaced_whole(chat):
    text = f"Look at what they said:\n\n{chat}\n\nCan the bot answer that?"
    got = redact.redact(text, KNOWN)
    assert got.counts.get("chat", 0) >= 1
    for line in chat.splitlines():
        assert line not in got.text
    assert got.text.startswith("Look at what they said:") and got.text.endswith("Can the bot answer that?")
    assert redact.detect(got.text, KNOWN) == {}


def test_pasted_content_is_not_the_persons_words_and_goes_whole():
    paste = '<pasted_content id="ab12">\nthey wrote: mail me at a.b@example.org\nand more\n</pasted_content id="ab12">'
    got = redact.redact(f"here is what the other chat said:\n{paste}\nfix it", KNOWN)
    assert got.text == "here is what the other chat said:\n<PASTE_1>\nfix it" and got.counts == {"paste": 1}


CLEAN = [
    "Fix the repo lane so a case from 35ac01f5c487124fb40fc7a94680178c22b78ac6 grades at its base.",
    "Run uv run pytest tests/test_history_importer.py::test_a_task_keeps_its_rows -q and see 4f9a7c2.",
    "Try mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit against HuggingFaceTB/SmolLM2-1.7B-Instruct.",
    "The server listens on 127.0.0.1:8082 and http://localhost:4000/v1; see RFC 5737 192.0.2.1.",
    "Paths like ~/localharness/runs and $LOCALHARNESS_HOME/repo-cache stay as written.",
    "Raise MAX_LINES to 400 and keep Draft202012Validator; mountainHeight=15 is fine.",
    "postgres.localharness.svc.cluster.local and host.docker.internal are the same on every machine.",
    "Close #1095 after PR #1100 merges; timestamps like 2026-10-22T12:30:45Z are fine.",
]


@pytest.mark.parametrize("text", CLEAN)
def test_clean_text_passes_unchanged(text):
    got = redact.redact(text, KNOWN)
    assert got.text == text and got.counts == {}
    assert redact.detect(text, KNOWN) == {}


def test_a_value_keeps_its_placeholder_and_a_second_value_gets_the_next():
    a, b = "one.person@example.org", "another@example.net"
    got = redact.redact(f"{a} wrote to {b}, then {a.upper()} again", KNOWN)
    assert got.text == "<EMAIL_1> wrote to <EMAIL_2>, then <EMAIL_1> again"
    assert got.counts == {"email": 3}


def test_redaction_is_idempotent_and_never_eats_its_own_placeholders():
    text = " ".join(c for _, c, _ in CANARIES) + "\n" + "\n".join(CHATS)
    once = redact.redact(text, KNOWN)
    assert redact.redact(once.text, KNOWN).text == once.text
    assert redact.detect(once.text, KNOWN) == {}
    assert set(once.counts) == {c for c, _, _ in CANARIES} | {"chat"}


def test_a_value_assigned_to_a_key_name_is_redacted_but_the_name_stays():
    got = redact.redact("export API_KEY=" + _rand(24) + " then password: " + _rand(12), KNOWN)
    assert got.text == "export API_KEY=<SECRET_1> then password: <SECRET_2>"


def test_known_here_names_this_machines_account():
    import getpass
    assert getpass.getuser() in redact.known_here().accounts


def test_known_here_reads_names_from_an_untracked_file(tmp_path):
    f = tmp_path / "names.txt"
    f.write_text("Quentavious\n\nzorbhandle\n", encoding="utf-8")
    known = redact.known_here([f])
    assert {"Quentavious", "zorbhandle"} <= set(known.names)
    assert redact.redact("ask zorbhandle", known).text == "ask <NAME_1>"


#: Made up, and never written in lower case anywhere in the repo, so the vocabulary cannot vouch for them.
NAME, HANDLE = "Zorvanna", "@quillfeather"


@pytest.mark.parametrize("text", [
    f"thanks to {NAME} for the report",
    f"{NAME} said the cache was stale.",
    f"[3] {NAME}: the build broke",
])
def test_a_made_up_name_is_name_like_wherever_it_sits(text):
    assert redact.name_like(text) == [NAME]


@pytest.mark.parametrize("text", [f"ping {HANDLE} about it", f"{HANDLE} hi, any news?"])
def test_a_handle_is_name_like(text):
    assert redact.name_like(text) == [HANDLE]


def test_words_decorators_and_safe_names_are_not_names():
    text = ("The importer reads Python files. Read the README before you Run it.\n"
            "    @pytest.mark.slow\n@property\n" + f"mail a.b@example.org; {NAME} again")
    assert redact.name_like(text) == [NAME]
    assert redact.name_like(text, safe=frozenset({NAME.lower()})) == []
    assert redact.name_like(f"see {HANDLE}", safe=frozenset({HANDLE[1:]})) == []


def test_the_committed_safe_list_vouches_for_no_canary():
    safe = redact.safe_names()
    assert NAME.lower() not in safe and HANDLE[1:] not in safe
    assert NAME.lower() not in redact.vocabulary()
