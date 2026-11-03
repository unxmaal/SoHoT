"""Metrics helpers."""

def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


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
