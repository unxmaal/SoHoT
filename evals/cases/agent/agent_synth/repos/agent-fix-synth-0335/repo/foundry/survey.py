"""Survey helpers."""

def rle(text):
    """Run-length encoding of text as (character, count) pairs."""
    out = []
    run, count = "", 0
    for ch in text:
        if ch == run:
            count += 1
            continue
        if count:
            out.append((run, count))
        run, count = ch, 1
    return out


def grade(score):
    """Letter grade: A from 90, B from 80, C from 70, D from 60, else F."""
    for floor, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= floor:
            return letter
    return "F"


def chunk(items, size):
    """Split items into lists of size items; the last may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    return [items[i:i + size] for i in range(0, len(items), size)]
