"""harness.suite_time reads a JUnit XML into where the time went. #720."""
from harness import suite_time

XML = """<?xml version="1.0"?>
<testsuites><testsuite>
""" + "".join(f'<testcase classname="tests.test_a" name="t{i}" time="1.0"/>' for i in range(99)) + """
<testcase classname="tests.test_b" name="slow" time="101.0"/>
</testsuite></testsuites>"""


def test_the_slowest_one_percent_and_the_files_are_summed(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(XML, encoding="utf-8")
    got = suite_time.summary(suite_time.times(path), top=2)
    assert got["tests"] == 100 and got["total_s"] == 200.0
    assert got["slowest_1pct"] == {"tests": 1, "seconds": 101.0, "share": 0.505}
    assert got["top_tests"][0] == ("tests/test_b.py::slow", 101.0)
    assert got["top_files"] == [("tests/test_b.py", 101.0), ("tests/test_a.py", 99.0)]
    assert "50.5% of the total" in suite_time.render(got)


def test_a_missing_report_says_so(tmp_path, capsys):
    assert suite_time.main([str(tmp_path / "none.xml")]) == 1
    assert "no JUnit XML" in capsys.readouterr().err
