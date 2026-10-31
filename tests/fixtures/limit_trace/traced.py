from harness import cuts

MAX_ITEMS = 5


def first(items):
    return cuts.take(items, MAX_ITEMS, "fixture_cap", "items past the cap")
