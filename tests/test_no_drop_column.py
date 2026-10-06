"""No test fakes an older store with DROP COLUMN; use the old_store fixture. #442."""
import re
from pathlib import Path

_DROP = re.compile(r"\bALTER\s+TABLE\s+\S+\s+DROP\s+COLUMN\b", re.I)
TESTS = Path(__file__).parent


def drop_columns(text: str) -> list[int]:
    return [n for n, line in enumerate(text.splitlines(), 1) if _DROP.search(line)]


def test_no_test_drops_a_column():
    found = [f"{p.name}:{n}" for p in sorted(TESTS.rglob("*.py"))
             for n in drop_columns(p.read_text(encoding="utf-8"))]
    assert found == [], f"build the old DDL with old_store instead: {found}"


def test_the_scan_sees_a_drop():
    """Negative control: a scan that cannot see the pattern passes vacuously."""
    sql = 'conn.execute("ALTER TABLE proposals DROP ' + 'column registry")'
    assert drop_columns("x = 1\n" + sql) == [2]
    assert drop_columns("ALTER TABLE p DROP\tCOLUMN c") == [1]
    assert drop_columns('f"ALTER TABLE proposals drop ' + 'column {col}"') == [1]
    assert drop_columns("ALTER TABLE p ADD COLUMN c") == []
