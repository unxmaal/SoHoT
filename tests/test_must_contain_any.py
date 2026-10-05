"""must_contain takes alternatives, so a check tests behaviour, not one spelling. #365."""
from pathlib import Path

import yaml

from evals.core import Case, score

PAGE = ('<!doctype html><html><body><form onsubmit="return check()">'
        '<input type="password"></form><script>function check(){return false}'
        '</script></body></html>')


def web(must):
    return Case(id="f", modality="web", prompt="p",
                assertions={"must_contain": must})


def test_any_one_alternative_satisfies_the_entry():
    assert score(web(["<form", ["addEventListener", "onsubmit"]]), PAGE).passed


def test_a_plain_entry_still_has_to_be_present():
    """Negative control."""
    got = score(web(["<form", "addEventListener"]), PAGE)
    assert not got.passed and "addEventListener" in got.detail


def test_none_of_the_alternatives_fails_and_names_them():
    got = score(web([["addEventListener", "oninput"]]), PAGE)
    assert not got.passed and "addEventListener or oninput" in got.detail


def test_form_validation_accepts_onsubmit():
    """The prompt says 'inline JavaScript on submit'; onsubmit answers it."""
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "evals" / "cases"
                          / "web" / "form-validation.yaml").read_text(encoding="utf-8"))
    assert ["addEventListener", "onsubmit"] in raw["assert"]["must_contain"]
