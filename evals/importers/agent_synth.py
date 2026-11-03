"""Generated agent cases: seeded multi-file repos in the hand set's read, edit, fix and refactor families. #603.

Every expected value in a test is computed by running the reference function here, so no
answer is typed. Edit cases grade on hidden tests run in the sandbox; read cases on the answer.
"""
from __future__ import annotations

import copy
import hashlib
import random
import re
import sys
from dataclasses import dataclass, field

from evals.importers import Imported, provenance

LANE = "agent"
VERSION = "1"
SEED = 603
COUNT = 360
SOURCE = f"generated:evals.importers.agent_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated agent cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/agent_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "agent-synth"
HIDDEN = "test_hidden.py"
EDIT_TOOLS = ["read_file", "write_file", "list_dir", "run_tests"]
READ_TOOLS = ["read_file", "list_dir"]


@dataclass(frozen=True)
class Call:
    args: tuple
    kwargs: tuple = ()


def A(*rows) -> tuple:
    return tuple(Call(tuple(r)) for r in rows)


def K(args, **kw) -> Call:
    return Call(tuple(args), tuple(sorted(kw.items())))


@dataclass(frozen=True)
class Feature:
    sentence: str
    params: str
    body: str
    inputs: tuple


@dataclass(frozen=True)
class Fn:
    name: str
    params: str
    doc: str
    body: str
    bugs: tuple = ()
    inputs: tuple = ()
    feature: Feature | None = None
    renames: tuple = ()
    imports: tuple = field(default=())


FNS = {f.name: f for f in (
    Fn("clamp", "value, low, high", "Limit value to the closed range from low to high.",
       "    return max(low, min(value, high))\n",
       bugs=("    return min(low, max(value, high))\n", "    return max(low, min(value, low))\n"),
       inputs=A((5, 0, 10), (-3, 0, 10), (15, 0, 10), (10, 0, 10), (0, 0, 10), (7, 7, 7), (-20, -30, -10)),
       feature=Feature("raise ValueError when low is greater than high", "value, low, high",
                       "    if low > high:\n        raise ValueError(\"low is above high\")\n"
                       "    return max(low, min(value, high))\n", A((5, 10, 0), (1, 3, 2))),
       renames=("bound", "limit_to")),
    Fn("chunk", "items, size", "Split items into lists of size items; the last may be shorter.",
       "    if size < 1:\n        raise ValueError(\"size must be at least 1\")\n"
       "    return [items[i:i + size] for i in range(0, len(items), size)]\n",
       bugs=("    if size < 1:\n        raise ValueError(\"size must be at least 1\")\n"
             "    return [items[i:i + size] for i in range(0, len(items) - size, size)]\n",),
       inputs=A(([1, 2, 3, 4, 5], 2), ([1, 2, 3, 4], 2), ([], 3), (["a"], 1), ([1, 2, 3], 5), ([1, 2], 0)),
       feature=Feature("add a keyword argument pad (default None); when pad is not None, fill the last "
                       "chunk with pad until it holds size items", "items, size, pad=None",
                       "    if size < 1:\n        raise ValueError(\"size must be at least 1\")\n"
                       "    out = [items[i:i + size] for i in range(0, len(items), size)]\n"
                       "    if pad is not None and out and len(out[-1]) < size:\n"
                       "        out[-1] = out[-1] + [pad] * (size - len(out[-1]))\n    return out\n",
                       (K(([1, 2, 3], 2), pad=0), K(([1, 2, 3, 4], 2), pad=0), K((["a", "b", "c"], 5), pad="-"))),
       renames=("batches", "split_into")),
    Fn("median", "xs", "Middle value; the mean of the two middle values for an even count.",
       "    if not xs:\n        raise ValueError(\"median of nothing\")\n    s = sorted(xs)\n    mid = len(s) // 2\n"
       "    if len(s) % 2:\n        return s[mid]\n    return (s[mid - 1] + s[mid]) / 2\n",
       bugs=("    if not xs:\n        raise ValueError(\"median of nothing\")\n    s = sorted(xs)\n"
             "    return s[len(s) // 2]\n",
             "    if not xs:\n        raise ValueError(\"median of nothing\")\n    s = sorted(xs)\n    mid = len(s) // 2\n"
             "    if len(s) % 2:\n        return s[mid]\n    return (s[mid] + s[mid + 1]) / 2\n"),
       inputs=A(([3, 1, 2],), ([4, 1, 3, 2],), ([5],), ([1, 2],), ([10, 2, 38, 23, 38, 23],), ([],)),
       feature=Feature("add a keyword argument default (default None); for an empty list return default "
                       "instead of raising, when default is not None", "xs, default=None",
                       "    if not xs:\n        if default is not None:\n            return default\n"
                       "        raise ValueError(\"median of nothing\")\n    s = sorted(xs)\n    mid = len(s) // 2\n"
                       "    if len(s) % 2:\n        return s[mid]\n    return (s[mid - 1] + s[mid]) / 2\n",
                       (K(([],), default=0), K(([],), default=-1), K(([1, 3],), default=0))),
       renames=("middle_value", "midpoint")),
    Fn("percent_change", "old, new", "Change from old to new as a percentage, rounded to 2 places.",
       "    if old == 0:\n        raise ValueError(\"no change from zero\")\n"
       "    return round((new - old) / old * 100, 2)\n",
       bugs=("    if old == 0:\n        raise ValueError(\"no change from zero\")\n"
             "    return round((new - old) / new * 100, 2)\n",),
       inputs=A((50, 75), (200, 150), (80, 80), (3, 4), (0, 5), (-10, -5)),
       feature=Feature("add a keyword argument places (default 2), the number of decimal places to round to",
                       "old, new, places=2",
                       "    if old == 0:\n        raise ValueError(\"no change from zero\")\n"
                       "    return round((new - old) / old * 100, places)\n",
                       (K((3, 4), places=0), K((3, 7), places=4))),
       renames=("pct_change", "growth_percent")),
    Fn("moving_average", "xs, k", "Mean of each window of k consecutive values, rounded to 3 places.",
       "    if k < 1:\n        raise ValueError(\"window must be at least 1\")\n"
       "    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]\n",
       bugs=("    if k < 1:\n        raise ValueError(\"window must be at least 1\")\n"
             "    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k)]\n",),
       inputs=A(([1, 2, 3, 4], 2), ([5], 1), ([1, 2, 3], 3), ([2, 4, 6, 8, 10], 3), ([1, 2], 0)),
       feature=Feature("raise ValueError when k is larger than the number of values", "xs, k",
                       "    if k < 1:\n        raise ValueError(\"window must be at least 1\")\n"
                       "    if k > len(xs):\n        raise ValueError(\"window is longer than the values\")\n"
                       "    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]\n",
                       A(([1, 2], 3), ([], 1))),
       renames=("rolling_mean", "window_means")),
    Fn("weighted_mean", "values, weights", "Mean of values weighted by weights, rounded to 3 places.",
       "    total = sum(weights)\n    if not total:\n        raise ValueError(\"weights sum to zero\")\n"
       "    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)\n",
       bugs=("    total = sum(weights)\n    if not total:\n        raise ValueError(\"weights sum to zero\")\n"
             "    return round(sum(v * w for v, w in zip(values, weights)) / len(weights), 3)\n",),
       inputs=A(([1, 2, 3], [1, 1, 1]), ([10, 20], [1, 3]), ([4], [2]), ([5, 5], [0, 0]), ([1, 2], [0.5, 1.5])),
       feature=Feature("raise ValueError when values and weights differ in length", "values, weights",
                       "    if len(values) != len(weights):\n        raise ValueError(\"one weight per value\")\n"
                       "    total = sum(weights)\n    if not total:\n        raise ValueError(\"weights sum to zero\")\n"
                       "    return round(sum(v * w for v, w in zip(values, weights)) / total, 3)\n",
                       A(([1, 2, 3], [1, 1]), ([4], [1, 2]))),
       renames=("weighted_average", "mean_by_weight")),
    Fn("dedupe", "items", "Items with repeats removed, first occurrences kept in order.",
       "    seen = set()\n    out = []\n    for item in items:\n        if item not in seen:\n"
       "            seen.add(item)\n            out.append(item)\n    return out\n",
       bugs=("    return sorted(set(items))\n",),
       inputs=A(([3, 1, 3, 2, 1],), (["b", "a", "b"],), ([],), ([1, 1, 1],)),
       feature=Feature("add a keyword argument ignore_case (default False); when it is true, strings that "
                       "differ only in case count as the same item and the first one is kept",
                       "items, ignore_case=False",
                       "    seen = set()\n    out = []\n    for item in items:\n"
                       "        key = item.lower() if ignore_case and isinstance(item, str) else item\n"
                       "        if key not in seen:\n            seen.add(key)\n            out.append(item)\n"
                       "    return out\n",
                       (K((["Tea", "tea", "Milk", "TEA"],), ignore_case=True), K((["a", "A"],), ignore_case=True))),
       renames=("unique_in_order", "drop_repeats")),
    Fn("parse_duration", "text", "Seconds in a duration such as 1h30m15s; units are h, m and s.",
       "    if not text or re.sub(r\"\\d+[hms]\", \"\", text):\n"
       "        raise ValueError(f\"bad duration: {text!r}\")\n    total = 0\n"
       "    for amount, unit in re.findall(r\"(\\d+)([hms])\", text):\n"
       "        total += int(amount) * {\"h\": 3600, \"m\": 60, \"s\": 1}[unit]\n    return total\n",
       bugs=("    if not text or re.sub(r\"\\d+[hms]\", \"\", text):\n"
             "        raise ValueError(f\"bad duration: {text!r}\")\n    total = 0\n"
             "    for amount, unit in re.findall(r\"(\\d+)([hms])\", text):\n"
             "        total += int(amount) * {\"h\": 360, \"m\": 60, \"s\": 1}[unit]\n    return total\n",
             "    if not text or re.sub(r\"\\d+[hms]\", \"\", text):\n"
             "        raise ValueError(f\"bad duration: {text!r}\")\n    total = 0\n"
             "    for amount, unit in re.findall(r\"(\\d)([hms])\", text):\n"
             "        total += int(amount) * {\"h\": 3600, \"m\": 60, \"s\": 1}[unit]\n    return total\n"),
       inputs=A(("1h30m",), ("45s",), ("2h",), ("1h1m1s",), ("",), ("5x",), ("10m5s",)),
       feature=Feature("accept a d unit for days of 86400 seconds", "text",
                       "    if not text or re.sub(r\"\\d+[dhms]\", \"\", text):\n"
                       "        raise ValueError(f\"bad duration: {text!r}\")\n    total = 0\n"
                       "    for amount, unit in re.findall(r\"(\\d+)([dhms])\", text):\n"
                       "        total += int(amount) * {\"d\": 86400, \"h\": 3600, \"m\": 60, \"s\": 1}[unit]\n"
                       "    return total\n", A(("1d",), ("2d3h",))),
       renames=("duration_seconds", "to_seconds"), imports=("re",)),
    Fn("is_leap", "year", "True for a Gregorian leap year.",
       "    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n",
       bugs=("    return year % 4 == 0 and year % 100 != 0\n", "    return year % 4 == 0\n"),
       inputs=A((2024,), (1900,), (2000,), (2023,), (2400,), (2100,)),
       renames=("leap_year", "has_feb_29")),
    Fn("word_count", "text", "Number of whitespace-separated words in text.",
       "    return len(text.split())\n",
       bugs=("    return len(text.split(\" \"))\n",),
       inputs=A(("a b",), ("  tea  and   milk ",), ("",), ("one",)),
       feature=Feature("add a keyword argument min_length (default 1); count only words with at least "
                       "min_length characters", "text, min_length=1",
                       "    return sum(1 for w in text.split() if len(w) >= min_length)\n",
                       (K(("a tea and milk",), **{"min_length": 3}), K(("go on",), **{"min_length": 5}))),
       renames=("count_words", "words_in")),
    Fn("paginate", "items, page, per_page", "The items on a 1-based page of per_page items.",
       "    if page < 1 or per_page < 1:\n        raise ValueError(\"page and per_page start at 1\")\n"
       "    start = (page - 1) * per_page\n    return items[start:start + per_page]\n",
       bugs=("    if page < 1 or per_page < 1:\n        raise ValueError(\"page and per_page start at 1\")\n"
             "    start = page * per_page\n    return items[start:start + per_page]\n",),
       inputs=A((list(range(1, 11)), 1, 3), (list(range(1, 11)), 4, 3), (list(range(1, 11)), 5, 3),
                ([], 1, 5), ([1, 2], 0, 2)),
       feature=Feature("accept page -1 for the last page (page 1 when items is empty)", "items, page, per_page",
                       "    if per_page < 1 or (page < 1 and page != -1):\n"
                       "        raise ValueError(\"page and per_page start at 1\")\n"
                       "    if page == -1:\n        page = max(1, -(-len(items) // per_page))\n"
                       "    start = (page - 1) * per_page\n    return items[start:start + per_page]\n",
                       A((list(range(1, 11)), -1, 3), (list(range(1, 10)), -1, 3), ([], -1, 4))),
       renames=("page_of", "slice_page")),
    Fn("bucket", "value, edges", "How many of the sorted edges value has reached.",
       "    return sum(1 for edge in edges if value >= edge)\n",
       bugs=("    return sum(1 for edge in edges if value > edge)\n",),
       inputs=A((5, [0, 5, 10]), (-1, [0, 5, 10]), (12, [0, 5, 10]), (0, [0, 5, 10]), (7, [])),
       feature=Feature("add a keyword argument labels (default None); when labels is given, return "
                       "labels[index] instead of the index", "value, edges, labels=None",
                       "    index = sum(1 for edge in edges if value >= edge)\n"
                       "    return index if labels is None else labels[index]\n",
                       (K((5, [0, 5, 10]), labels=["none", "low", "mid", "high"]),
                        K((-2, [0]), labels=["below", "above"]))),
       renames=("band_of", "bin_index")),
    Fn("running_total", "xs", "The cumulative sums of xs.",
       "    out = []\n    total = 0\n    for x in xs:\n        total += x\n        out.append(total)\n    return out\n",
       bugs=("    out = []\n    total = xs[0] if xs else 0\n    for x in xs:\n        total += x\n"
             "        out.append(total)\n    return out\n",),
       inputs=A(([1, 2, 3],), ([],), ([5],), ([2, -2, 2],)),
       feature=Feature("add a keyword argument start (default 0), added before the first item", "xs, start=0",
                       "    out = []\n    total = start\n    for x in xs:\n        total += x\n"
                       "        out.append(total)\n    return out\n",
                       (K(([1, 2],), start=10), K(([],), start=4), K(([3],), start=-3))),
       renames=("cumulative", "prefix_sums")),
    Fn("invert", "mapping", "Each value of mapping with the sorted keys that map to it.",
       "    out = {}\n    for key, value in mapping.items():\n        out.setdefault(value, []).append(key)\n"
       "    return {value: sorted(keys) for value, keys in out.items()}\n",
       bugs=("    out = {}\n    for key, value in mapping.items():\n        out[value] = [key]\n"
             "    return {value: sorted(keys) for value, keys in out.items()}\n",),
       inputs=A(({"a": 1, "b": 2, "c": 1},), ({},), ({"x": "y"},), ({"q": 0, "p": 0, "r": 0},)),
       renames=("keys_by_value", "reverse_map")),
    Fn("rle", "text", "Run-length encoding of text as (character, count) pairs.",
       "    out = []\n    run, count = \"\", 0\n    for ch in text:\n        if ch == run:\n"
       "            count += 1\n            continue\n        if count:\n            out.append((run, count))\n"
       "        run, count = ch, 1\n    if count:\n        out.append((run, count))\n    return out\n",
       bugs=("    out = []\n    run, count = \"\", 0\n    for ch in text:\n        if ch == run:\n"
             "            count += 1\n            continue\n        if count:\n            out.append((run, count))\n"
             "        run, count = ch, 1\n    return out\n",),
       inputs=A(("aaab",), ("",), ("abc",), ("zz",)),
       renames=("run_lengths", "encode_runs")),
    Fn("format_cents", "cents", "Cents as dollars with thousands separators, such as -$1,234.56.",
       "    sign = \"-\" if cents < 0 else \"\"\n    cents = abs(cents)\n"
       "    return f\"{sign}${cents // 100:,}.{cents % 100:02d}\"\n",
       bugs=("    return f\"${cents / 100:,.2f}\"\n",
             "    sign = \"-\" if cents < 0 else \"\"\n    cents = abs(cents)\n"
             "    return f\"{sign}${cents // 100:,}.{cents % 100}\"\n"),
       inputs=A((0,), (123456,), (-105,), (5,), (100000000,)),
       feature=Feature("add a keyword argument symbol (default \"$\") written in place of the dollar sign",
                       "cents, symbol=\"$\"",
                       "    sign = \"-\" if cents < 0 else \"\"\n    cents = abs(cents)\n"
                       "    return f\"{sign}{symbol}{cents // 100:,}.{cents % 100:02d}\"\n",
                       (K((123456,), symbol="GBP "), K((-105,), symbol="EUR "))),
       renames=("money", "dollars")),
    Fn("merge_ranges", "ranges", "Overlapping or touching (start, end) ranges merged, sorted by start.",
       "    out = []\n    for start, end in sorted(ranges):\n        if out and start <= out[-1][1]:\n"
       "            out[-1] = (out[-1][0], max(out[-1][1], end))\n        else:\n"
       "            out.append((start, end))\n    return out\n",
       bugs=("    out = []\n    for start, end in sorted(ranges):\n        if out and start < out[-1][1]:\n"
             "            out[-1] = (out[-1][0], max(out[-1][1], end))\n        else:\n"
             "            out.append((start, end))\n    return out\n",
             "    out = []\n    for start, end in sorted(ranges):\n        if out and start <= out[-1][1]:\n"
             "            out[-1] = (out[-1][0], end)\n        else:\n"
             "            out.append((start, end))\n    return out\n"),
       inputs=A(([(1, 3), (3, 5)],), ([(5, 6), (1, 2)],), ([(1, 10), (2, 3)],), ([],), ([(4, 8), (1, 5)],)),
       feature=Feature("also merge ranges that are adjacent, such as (1, 2) and (3, 4)", "ranges",
                       "    out = []\n    for start, end in sorted(ranges):\n        if out and start <= out[-1][1] + 1:\n"
                       "            out[-1] = (out[-1][0], max(out[-1][1], end))\n        else:\n"
                       "            out.append((start, end))\n    return out\n",
                       A(([(1, 2), (3, 4)],), ([(7, 9), (1, 6)],))),
       renames=("join_ranges", "coalesce")),
    Fn("grade", "score", "Letter grade: A from 90, B from 80, C from 70, D from 60, else F.",
       "    for floor, letter in ((90, \"A\"), (80, \"B\"), (70, \"C\"), (60, \"D\")):\n"
       "        if score >= floor:\n            return letter\n    return \"F\"\n",
       bugs=("    for floor, letter in ((90, \"A\"), (80, \"B\"), (70, \"C\"), (60, \"D\")):\n"
             "        if score > floor:\n            return letter\n    return \"F\"\n",),
       inputs=A((95,), (90,), (85,), (80,), (61,), (59,), (0,)),
       feature=Feature("add a keyword argument plus (default False); when it is true, a B, C or D score in "
                       "the top three points of its band gets a + (88 is B+)", "score, plus=False",
                       "    for floor, letter in ((90, \"A\"), (80, \"B\"), (70, \"C\"), (60, \"D\")):\n"
                       "        if score >= floor:\n"
                       "            if plus and letter != \"A\" and score >= floor + 7:\n"
                       "                return letter + \"+\"\n            return letter\n    return \"F\"\n",
                       (K((88,), plus=True), K((95,), plus=True), K((86,), plus=True), K((69,), plus=True))),
       renames=("letter_grade", "mark_of")),
    Fn("luhn_valid", "number", "True when the digits of number pass the Luhn checksum.",
       "    digits = [int(d) for d in number if d.isdigit()]\n    total = 0\n"
       "    for i, d in enumerate(reversed(digits)):\n        if i % 2:\n            d *= 2\n"
       "            if d > 9:\n                d -= 9\n        total += d\n"
       "    return bool(digits) and total % 10 == 0\n",
       bugs=("    digits = [int(d) for d in number if d.isdigit()]\n    total = 0\n"
             "    for i, d in enumerate(digits):\n        if i % 2:\n            d *= 2\n"
             "            if d > 9:\n                d -= 9\n        total += d\n"
             "    return bool(digits) and total % 10 == 0\n",),
       inputs=A(("4539 1488 0343 6467",), ("79927398713",), ("79927398710",), ("",), ("059",)),
       renames=("checksum_ok", "passes_luhn")),
    Fn("top_n", "counts, n", "The n keys with the highest counts, ties in key order.",
       "    return sorted(counts, key=lambda k: (-counts[k], k))[:n]\n",
       bugs=("    return sorted(counts, key=lambda k: (counts[k], k), reverse=True)[:n]\n",),
       inputs=A(({"tea": 3, "milk": 3, "jam": 1}, 2), ({"a": 1}, 5), ({}, 2), ({"x": 2, "y": 5, "z": 2}, 2)),
       feature=Feature("add a keyword argument min_count (default 0); leave out keys whose count is below "
                       "min_count", "counts, n, min_count=0",
                       "    kept = [k for k in counts if counts[k] >= min_count]\n"
                       "    return sorted(kept, key=lambda k: (-counts[k], k))[:n]\n",
                       (K(({"tea": 3, "milk": 1, "jam": 2}, 5), **{"min_count": 2}),)),
       renames=("most_common", "leaders")),
    Fn("truncate_words", "text, n", "The first n words of text, with ... when words were cut.",
       "    words = text.split()\n    if len(words) <= n:\n        return \" \".join(words)\n"
       "    return \" \".join(words[:n]) + \"...\"\n",
       bugs=("    words = text.split()\n    if len(words) < n:\n        return \" \".join(words)\n"
             "    return \" \".join(words[:n]) + \"...\"\n",),
       inputs=A(("the quick brown fox", 2), ("tea time", 2), ("", 3), ("one two three", 1)),
       feature=Feature("add a keyword argument ellipsis (default \"...\") put after a cut text",
                       "text, n, ellipsis=\"...\"",
                       "    words = text.split()\n    if len(words) <= n:\n        return \" \".join(words)\n"
                       "    return \" \".join(words[:n]) + ellipsis\n",
                       (K(("the quick brown fox", 1), ellipsis=" [more]"),)),
       renames=("shorten", "first_words")),
    Fn("snake_case", "name", "A CamelCase name in snake_case.",
       "    return re.sub(r\"(?<!^)(?=[A-Z])\", \"_\", name).lower()\n",
       bugs=("    return re.sub(r\"(?=[A-Z])\", \"_\", name).lower()\n",),
       inputs=A(("OrderTotal",), ("plain",), ("A",), ("ShipToCity",)),
       feature=Feature("also turn hyphens and spaces into underscores", "name",
                       "    out = re.sub(r\"(?<!^)(?=[A-Z])\", \"_\", name).lower()\n"
                       "    return re.sub(r\"[-\\s_]+\", \"_\", out)\n", A(("Order Total",), ("tea-time",))),
       renames=("to_snake", "underscored"), imports=("re",)),
)}

PACKAGES = ("depot", "tally", "harbor", "mill", "orchard", "foundry", "atlas", "beacon", "quarry", "meadow",
            "kiln", "granary", "wharf", "lantern", "compass")
MODULES = ("pricing", "metrics", "stock", "ledger", "shipping", "survey", "timesheet", "catalog", "orders",
           "sensors", "billing", "rosters", "routes", "payroll", "budget", "weather", "tickets", "fleet",
           "kitchen", "archive")
NEW_MODULES = ("helpers", "common", "shared", "toolkit", "core_math", "numbers", "textual", "tools")
REPORTS = ("report", "summary", "digest", "dashboard", "overview")
NOUNS = ("dock", "crate", "berth", "ferry", "cargo", "pallet", "quay", "mooring", "tide", "harbor", "buoy",
         "rope", "anchor", "deck", "hull", "sail", "mast", "keel", "lantern", "barge")
SUFFIXES = ("figure", "line", "entry", "summary", "row", "total", "check", "view")
VERBS = ("load", "parse", "merge", "split", "apply", "render", "resolve", "validate", "lookup", "rank",
         "allocate", "estimate", "normalize", "reconcile", "stage", "flush")
KEYS = (("port", "TCP port", 1024, 65000), ("workers", "number of worker processes", 11, 97),
        ("pool_size", "database connection pool size", 12, 400), ("timeout_s", "request timeout in seconds",
                                                                    15, 900),
        ("cache_ttl_s", "cache lifetime in seconds", 120, 86000), ("max_upload_kb", "upload limit in kilobytes",
                                                                    512, 99000),
        ("retry_limit", "retry limit", 13, 99))
ENVS = ("development", "staging", "production")
CONSTANTS = ("RETRY_LIMIT", "BATCH_SIZE", "MAX_WORKERS", "PAGE_SIZE", "FLUSH_EVERY", "QUEUE_DEPTH",
             "CHUNK_BYTES", "IDLE_TIMEOUT_S")
#: Kinds and the hand set's family each id carries.
KINDS = {"fix": "fix", "trace": "fix", "edit": "edit", "rename": "refactor", "move": "refactor",
         "config": "read", "locate": "read", "constant": "read"}
#: Kinds whose untouched repo fails its own visible tests.
BUGGY = ("fix", "trace")
MAX_STEPS = {"fix": 16, "trace": 16, "edit": 12, "rename": 16, "move": 16, "config": 12, "locate": 12,
             "constant": 12}


# --- running the references ---------------------------------------------------

def source(fn: Fn, body: str | None = None, params: str | None = None, name: str | None = None) -> str:
    return (f"def {name or fn.name}({fn.params if params is None else params}):\n"
            f"    \"\"\"{fn.doc}\"\"\"\n{fn.body if body is None else body}")


def outcome(fn: Fn, call: Call, body: str | None = None, params: str | None = None) -> tuple:
    """('ok', value) or ('raise', exception name) for one call of fn as written by body."""
    space: dict = {}
    exec("".join(f"import {m}\n" for m in fn.imports) + source(fn, body, params), space)  # noqa: S102
    try:
        return "ok", space[fn.name](*copy.deepcopy(call.args), **dict(copy.deepcopy(call.kwargs)))
    except Exception as exc:  # noqa: BLE001
        return "raise", type(exc).__name__


def caught(fn: Fn, bug: int) -> list[Call]:
    """The inputs whose outcome tells bug apart from the reference."""
    got = [c for c in fn.inputs if outcome(fn, c) != outcome(fn, c, fn.bugs[bug])]
    if not got:
        raise ValueError(f"{fn.name}: no input catches bug {bug}")
    return got


def changed(fn: Fn) -> list[Call]:
    """The feature inputs it changes; refuses a feature that changes an old input."""
    f = fn.feature
    for c in fn.inputs:
        if outcome(fn, c) != outcome(fn, c, f.body, f.params):
            raise ValueError(f"{fn.name}: the feature changes {c}")
    got = [c for c in f.inputs if outcome(fn, c) != outcome(fn, c, f.body, f.params)]
    if not got:
        raise ValueError(f"{fn.name}: no feature input differs from the old function")
    return got


def audit() -> None:
    """Every bug is caught by some input and every feature changes only its own inputs."""
    for fn in FNS.values():
        for b in range(len(fn.bugs)):
            caught(fn, b)
        if fn.feature:
            changed(fn)


# --- rendering ----------------------------------------------------------------

def _arglist(call: Call) -> str:
    return ", ".join([repr(a) for a in call.args] + [f"{k}={v!r}" for k, v in call.kwargs])


def _check(call_src: str, got: tuple, indent: str = "        ") -> str:
    kind, value = got
    if kind == "raise":
        return f"{indent}with self.assertRaises({value}):\n{indent}    {call_src}\n"
    return f"{indent}self.assertEqual({call_src}, {value!r})\n"


def _module(doc: str, fns: list, bodies: dict | None = None, head: str = "") -> str:
    bodies = bodies or {}
    imports = sorted({m for fn in fns for m in fn.imports})
    out = f"\"\"\"{doc}\"\"\"\n" + "".join(f"import {m}\n" for m in imports) + head
    parts = []
    for fn in fns:
        body, params = bodies.get(fn.name, (None, None))
        parts.append(source(fn, body, params))
    return out + ("\n\n" if imports or head else "\n") + "\n\n".join(parts)


def _test_file(cls: str, imports: str, methods: list[tuple[str, str]]) -> str:
    out = f"import unittest\n\n{imports}\n\n\nclass {cls}(unittest.TestCase):\n"
    return out + "\n".join(f"    def test_{name}(self):\n{body}" for name, body in methods)


def _cls(text: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\W]+", text) if w)


# --- the kinds ----------------------------------------------------------------

def _package(rng, n_modules: int, per: tuple) -> list[tuple[str, list]]:
    """Distinct module names, each holding per[0] to per[1] functions no other module holds."""
    sizes = [rng.randint(*per) for _ in range(n_modules)]
    picked = iter(rng.sample(sorted(FNS), sum(sizes)))
    return [(m, [FNS[next(picked)] for _ in range(k)]) for m, k in zip(rng.sample(MODULES, n_modules), sizes)]


def _visible(fn: Fn, extra: list) -> list[Call]:
    got = list(fn.inputs[:2])
    for c in extra:
        if c not in got:
            got.append(c)
            break
    return got


def _fix(rng, pkg: str, trace: bool) -> dict:
    mods = _package(rng, rng.randint(3, 5), (2, 3))
    with_bugs = [(m, fn) for m, fns in mods for fn in fns if fn.bugs]
    nbugs = 1 if trace else rng.choice((1, 2, 2, 3))
    planted, used = {}, set()
    for m, fn in rng.sample(with_bugs, len(with_bugs)):
        if len(planted) == nbugs:
            break
        if m in used and not trace:
            continue
        planted[fn.name] = rng.randrange(len(fn.bugs))
        used.add(m)
    files, solution = {f"{pkg}/__init__.py": ""}, {}
    for m, fns in mods:
        doc = f"{m.capitalize()} helpers."
        bodies = {n: (fn.bugs[planted[n]], None) for fn in fns for n in [fn.name] if n in planted}
        files[f"{pkg}/{m}.py"] = _module(doc, fns, bodies)
        if bodies:
            solution[f"{pkg}/{m}.py"] = _module(doc, fns)
    hidden = []
    for m, fns in mods:
        for fn in fns:
            hidden.append((f"{m}_{fn.name}", "".join(_check(f"{m}.{fn.name}({_arglist(c)})", outcome(fn, c))
                                                    for c in fn.inputs)))
    imports = "\n".join(f"from {pkg} import {m}" for m, _ in mods)
    if trace:
        report = rng.choice(REPORTS)
        wraps = _wrappers(rng, [(m, fn) for m, fns in mods for fn in fns][:4] +
                          [(m, fn) for m, fns in mods for fn in fns if fn.name in planted])
        files[f"{pkg}/{report}.py"] = _wrapper_module(pkg, report, wraps, style=rng.choice(("module", "name")))
        methods = [(w, "".join(_wrap_check(report, w, fn, c) for c in
                                _visible(fn, caught(fn, planted[fn.name]) if fn.name in planted else [])))
                   for w, m, fn in wraps]
        files[f"tests/test_{report}.py"] = _test_file(_cls(report), f"from {pkg} import {report}", methods)
        hidden += [(f"{report}_{w}", "".join(_wrap_check(report, w, fn, c) for c in fn.inputs))
                   for w, m, fn in wraps]
        imports += f"\nfrom {pkg} import {report}"
        prompt = f"tests/test_{report}.py fails. Find the bug and fix it in the code, not in the test."
    else:
        for m, fns in mods:
            methods = []
            for fn in fns:
                extra = caught(fn, planted[fn.name]) if fn.name in planted else []
                methods.append((fn.name, "".join(_check(f"{m}.{fn.name}({_arglist(c)})", outcome(fn, c))
                                                 for c in _visible(fn, extra))))
            files[f"tests/test_{m}.py"] = _test_file(_cls(m), f"from {pkg} import {m}", methods)
        prompt = (f"Tests under tests/ fail. Find what is wrong in {pkg}/ and fix the code, not the tests. "
                  "Run the tests when done.")
    return {"prompt": prompt, "files": files, "solution": solution,
            "hidden": _test_file("Hidden", imports, hidden)}


def _wrappers(rng, picks: list) -> list[tuple[str, str, Fn]]:
    seen, out = set(), []
    names = rng.sample([f"{n}_{s}" for n in NOUNS for s in SUFFIXES], len(picks))
    for (m, fn), w in zip(picks, names):
        if fn.name not in seen:
            seen.add(fn.name)
            out.append((w, m, fn))
    return out


def _wrapper_module(pkg: str, name: str, wraps: list, style: str) -> str:
    """A module of one-line wrappers; style 'module' imports modules, 'name' imports the functions."""
    if style == "module":
        lines = [f"from {pkg} import {m}" for m in sorted({m for _, m, _ in wraps})]
    else:
        by: dict = {}
        for _, m, fn in wraps:
            by.setdefault(m, []).append(fn.name)
        lines = [f"from {pkg}.{m} import {', '.join(sorted(ns))}" for m, ns in sorted(by.items())]
    body = [f"def {w}({fn.params}):\n    \"\"\"One {w.replace('_', ' ')} for the {name} page.\"\"\"\n"
            f"    return {{{w!r}: {f'{m}.{fn.name}' if style == 'module' else fn.name}({fn.params})}}\n"
            for w, m, fn in wraps]
    return (f"\"\"\"{name.capitalize()} built from the package's helpers.\"\"\"\n" + "\n".join(lines)
            + "\n\n\n" + "\n\n".join(body))


def _wrap_check(mod: str, w: str, fn: Fn, call: Call) -> str:
    got = outcome(fn, call)
    return _check(f"{mod}.{w}({_arglist(call)})", ("ok", {w: got[1]}) if got[0] == "ok" else got)


def _edit(rng, pkg: str) -> dict:
    mods = _package(rng, rng.randint(2, 4), (2, 3))
    targets = [(m, fn) for m, fns in mods for fn in fns if fn.feature]
    if not targets:
        raise _Redraw
    m, fn = rng.choice(targets)
    changed(fn)
    files, solution = {f"{pkg}/__init__.py": ""}, {}
    hidden = []
    for mm, fns in mods:
        doc = f"{mm.capitalize()} helpers."
        files[f"{pkg}/{mm}.py"] = _module(doc, fns)
        if mm == m:
            solution[f"{pkg}/{mm}.py"] = _module(doc, fns, {fn.name: (fn.feature.body, fn.feature.params)})
        methods = [(f.name, "".join(_check(f"{mm}.{f.name}({_arglist(c)})", outcome(f, c))
                                    for c in f.inputs[:3])) for f in fns]
        files[f"tests/test_{mm}.py"] = _test_file(_cls(mm), f"from {pkg} import {mm}", methods)
        for f in fns:
            hidden.append((f"{mm}_{f.name}", "".join(_check(f"{mm}.{f.name}({_arglist(c)})", outcome(f, c))
                                                    for c in f.inputs)))
    new = fn.feature
    hidden.append(("feature", "".join(_check(f"{m}.{fn.name}({_arglist(c)})",
                                             outcome(fn, c, new.body, new.params)) for c in new.inputs)))
    prompt = (f"Change {pkg}.{m}.{fn.name}: {new.sentence}. Other behaviour must not change. "
              "Run the tests when done.")
    imports = "\n".join(f"from {pkg} import {mm}" for mm, _ in mods)
    return {"prompt": prompt, "files": files, "solution": solution,
            "hidden": _test_file("Hidden", imports, hidden)}


class _Redraw(Exception):
    """This draw cannot make the kind's case; the row is drawn again."""


def _caller(pkg: str, m: str, cfns: list, wraps: list, style: str, t_mod: str, t_name: str) -> str:
    """A module of its own helpers plus wrappers that call the target, imported in `style`."""
    imp = f"from {pkg} import {t_mod}" if style == "module" else f"from {pkg}.{t_mod} import {t_name}"
    call = f"{t_mod}.{t_name}" if style == "module" else t_name
    text = _module(f"{m.capitalize()} helpers.", cfns, head=imp + "\n")
    for w, _, fn in wraps:
        text += (f"\n\ndef {w}({fn.params}):\n    \"\"\"One {w.replace('_', ' ')} for the {m} page.\"\"\"\n"
                 f"    return {{{w!r}: {call}({fn.params})}}\n")
    return text


def _refactor(rng, pkg: str, move: bool) -> dict:
    mods = _package(rng, 1 + rng.randint(2, 4), (1, 2))
    (home, fns), callers = mods[0], mods[1:]
    target = rng.choice(fns)
    others = [f for f in fns if f is not target]
    if move and not others:
        raise _Redraw
    old, new_name = target.name, rng.choice(target.renames)
    new_mod = rng.choice([n for n in NEW_MODULES if n not in dict(mods)])
    styles = {m: rng.choice(("module", "name")) for m, _ in callers}
    wraps_of = {m: _wrappers(rng, [(home, target)]) for m, _ in callers}
    doc = f"{home.capitalize()} helpers."

    def render(after: bool) -> dict:
        t_mod = new_mod if (after and move) else home
        t_name = new_name if (after and not move) else old
        out = {f"{pkg}/__init__.py": ""}
        if after and move:
            out[f"{pkg}/{home}.py"] = _module(doc, others)
            out[f"{pkg}/{new_mod}.py"] = _module("Helpers shared across the package.", [target])
        else:
            out[f"{pkg}/{home}.py"] = _module(doc, fns).replace(f"def {old}(", f"def {t_name}(")
        for m, cfns in callers:
            out[f"{pkg}/{m}.py"] = _caller(pkg, m, cfns, wraps_of[m], styles[m], t_mod, t_name)
            methods = [(w, "".join(_wrap_check(m, w, f, c) for c in f.inputs[:2])) for w, _, f in wraps_of[m]]
            methods += [(f.name, "".join(_check(f"{m}.{f.name}({_arglist(c)})", outcome(f, c))
                                         for c in f.inputs[:2])) for f in cfns]
            out[f"tests/test_{m}.py"] = _test_file(_cls(m), f"from {pkg} import {m}", methods)
        direct = [(t_name, "".join(_check(f"{t_name}({_arglist(c)})", outcome(target, c))
                                   for c in target.inputs[:3]))]
        direct += [(f.name, "".join(_check(f"{home}.{f.name}({_arglist(c)})", outcome(f, c))
                                    for c in f.inputs[:2])) for f in others]
        imp = f"from {pkg}.{t_mod} import {t_name}" + (f"\nfrom {pkg} import {home}" if others else "")
        out[f"tests/test_{home}.py"] = _test_file(_cls(home), imp, direct)
        return out

    before, after = render(False), render(True)
    solution = {k: v for k, v in after.items() if before.get(k) != v}
    t_mod, t_name = (new_mod, old) if move else (home, new_name)
    checks = [("target", "".join(_check(f"{t_mod}.{t_name}({_arglist(c)})", outcome(target, c))
                                 for c in target.inputs))]
    checks += [(f"{m}_{w}", "".join(_wrap_check(m, w, f, c) for c in f.inputs))
               for m, _ in callers for w, _, f in wraps_of[m]]
    if move:
        checks.append(("moved", f"        new = pathlib.Path({f'{pkg}/{new_mod}.py'!r}).read_text(encoding=\"utf-8\")\n"
                                "        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == "
                                f"{old!r} for n in ast.walk(ast.parse(new))))\n"
                                f"        text = pathlib.Path({f'{pkg}/{home}.py'!r}).read_text(encoding=\"utf-8\")\n"
                                f"        self.assertNotIn({old!r}, names(text))\n"))
        prompt = (f"Move {old} out of {pkg}/{home}.py into a new module {pkg}/{new_mod}.py and update every "
                  f"import of it in {pkg}/ and tests/. {pkg}/{home}.py must neither define nor import {old} "
                  "afterwards. Output must not change. Run the tests.")
    else:
        checks.append(("old_name_gone",
                       f"        self.assertFalse(hasattr({home}, {old!r}))\n"
                       f"        for f in [*pathlib.Path({pkg!r}).rglob(\"*.py\"), "
                       "*pathlib.Path(\"tests\").rglob(\"*.py\")]:\n"
                       f"            self.assertNotIn({old!r}, names(f.read_text(encoding=\"utf-8\")), f)\n"))
        prompt = (f"Rename {pkg}.{home}.{old} to {new_name} and update every caller in {pkg}/ and tests/. "
                  f"Do not keep the old name as an alias: no code in {pkg}/ or tests/ may still use {old} "
                  "afterwards. Run the tests.")
    used = sorted({t_mod, home, *(m for m, _ in callers)})
    imports = ("import ast\nimport pathlib\n\n" + "\n".join(f"from {pkg} import {m}" for m in used) + "\n\n\n"
               + NAMES)
    return {"prompt": prompt, "files": before, "solution": solution,
            "hidden": _test_file("Hidden", imports, checks)}


#: Every identifier a module's code uses, so a docstring word never reads as the old name.
NAMES = ("def names(text):\n    out = set()\n    for n in ast.walk(ast.parse(text)):\n"
         "        if isinstance(n, ast.Name):\n            out.add(n.id)\n"
         "        elif isinstance(n, ast.Attribute):\n            out.add(n.attr)\n"
         "        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):\n            out.add(n.name)\n"
         "        elif isinstance(n, ast.alias):\n            out.update({n.name.split(\".\")[-1], n.asname})\n"
         "    return out")


def _values(rng, lo: int, hi: int, n: int) -> list[int]:
    return rng.sample(range(lo, hi), n)


def _config(rng) -> dict:
    key, label, lo, hi = rng.choice(KEYS)
    env = rng.choice(ENVS)
    mode = rng.choice(("env", "base", "code"))
    others = [e for e in ENVS if e != env]
    base, own, comment, readme, code, o1, o2, stray = _values(rng, lo, hi, 8)
    noise = {k: _values(rng, lo2, hi2, 4) for k, _, lo2, hi2 in KEYS if k != key}
    answer = {"env": own, "base": base, "code": code}[mode]
    stray_env = rng.choice(others)
    overrides = {stray_env: {key: stray}}
    if mode == "code":
        overrides.setdefault(env, {})[key] = code
    nk = rng.choice(sorted(noise))
    overrides.setdefault(rng.choice(ENVS), {}).setdefault(nk, noise[nk][3])
    base_ini = "[service]\n" + "".join(f"{k} = {noise[k][0]}\n" if k != key else f"{k} = {base}\n"
                                       for k, *_ in KEYS)
    files = {"config/base.ini": base_ini}
    for e, v in ((env, own), (others[0], o1), (others[1], o2)):
        lines = ["[service]"]
        if e == env:
            lines.append(f"; {key} = {comment}")
            if mode != "base":
                lines.append(f"{key} = {v}")
        else:
            lines.append(f"{key} = {v}")
        lines.append(f"{nk} = {noise[nk][1 + ENVS.index(e) % 2]}")
        files[f"config/{e}.ini"] = "\n".join(lines) + "\n"
    ov = "".join(f"    {e!r}: {{{', '.join(f'{k!r}: {str(v)!r}' for k, v in sorted(d.items()))}}},\n"
                 for e, d in sorted(overrides.items()))
    files["app/__init__.py"] = ""
    files["app/settings.py"] = (
        "\"\"\"Service settings: config/base.ini, then config/<env>.ini over it, then OVERRIDES.\"\"\"\n"
        "import configparser\nimport os\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parent.parent\n"
        "#: Values pinned in code; they win over the ini files.\nOVERRIDES = {\n" + ov + "}\n\n\n"
        "def load(env=None):\n    env = env or os.environ.get(\"APP_ENV\", \"development\")\n"
        "    parser = configparser.ConfigParser()\n"
        "    parser.read([ROOT / \"config\" / \"base.ini\", ROOT / \"config\" / f\"{env}.ini\"])\n"
        "    values = dict(parser[\"service\"])\n    values.update(OVERRIDES.get(env, {}))\n    return values\n")
    files["app/server.py"] = ("\"\"\"Entry point.\"\"\"\nfrom app import settings\n\n\ndef main():\n"
                              "    values = settings.load()\n    return int(values[\"port\"]), int(values[\"workers\"])\n")
    files["README.txt"] = (f"Service\n\nSettings live in config/. Out of the box the {label} is {readme}.\n"
                           "Set APP_ENV to development, staging or production.\n")
    shown = [base, comment, readme, o1, o2, stray] + ([own] if mode != "base" else []) + \
        ([code] if mode == "code" else [])
    return {"prompt": f"What {label} does this service use when it runs in {env}? Answer with the number.",
            "files": files, "answer": str(answer), "decoys": [str(v) for v in shown if v != answer],
            "check": {"env": env, "key": key}}


def _ident(rng, n: int) -> list[str]:
    return rng.sample([f"{v}_{x}" for v in VERBS for x in NOUNS], n)


def _locate(rng, pkg: str) -> dict:
    subs = rng.sample(("io", "model", "util", "service", "store", "net", "jobs"), 3)
    mods = rng.sample(MODULES, 6)
    paths = [f"{pkg}/{subs[i % 3]}/{m}.py" for i, m in enumerate(mods)]
    names = _ident(rng, 10)
    target = names[0]
    home, legacy, *users = rng.sample(paths, 4)
    if any(a in b for a in paths for b in paths if a != b):
        raise _Redraw
    files = {f"{pkg}/__init__.py": ""}
    files.update({f"{pkg}/{s}/__init__.py": "" for s in subs})
    filler = iter(names[1:])
    mod_of = {p: p[:-3].replace("/", ".") for p in paths}
    for p in paths:
        lines, body = [f"\"\"\"{p.rsplit('/', 1)[1][:-3].capitalize()} module.\"\"\""], []
        if p in users:
            lines.append(f"from {mod_of[home]} import {target}")
            body.append(f"def {next(filler)}(rows):\n    return [{target}(r) for r in rows]\n")
        if p == home:
            body.append(f"def {target}(row):\n    \"\"\"One row ready to store.\"\"\"\n"
                        f"    return {{k: v for k, v in row.items() if v is not None}}\n")
        if p == legacy:
            body.append(f"def {target}_legacy(row):\n    \"\"\"Kept for old callers.\"\"\"\n    return dict(row)\n")
        body.append(f"def {next(filler)}(values):\n    return sorted(values)\n")
        files[p] = "\n".join(lines) + "\n\n\n" + "\n\n".join(body)
    return {"prompt": f"Which file defines the function {target}? Answer with its path relative to the "
                      "repository root.",
            "files": files, "answer": home, "decoys": [legacy, *users], "check": {"name": target}}


def _constant(rng, pkg: str) -> dict:
    name = rng.choice(CONSTANTS)
    hops = rng.choice((1, 2, 3))
    chain = ["defaults", "settings", "tuning"][:hops]
    vals = _values(rng, 100, 9999, 6)
    over = rng.randrange(hops + 1)
    assigned = {chain[0]: vals[0]}
    if 0 < over < hops:
        assigned[chain[over]] = vals[over]
    if over == hops and hops > 1:
        assigned[chain[-1]] = vals[hops]
    answer = assigned[[m for m in chain if m in assigned][-1]]
    files = {f"{pkg}/__init__.py": ""}
    for i, m in enumerate(chain):
        lines = [f"\"\"\"{m.capitalize()} for the package.\"\"\""]
        if i:
            lines.append(f"from {pkg}.{chain[i - 1]} import *  # noqa: F403")
        if m in assigned:
            lines.append(f"{name} = {assigned[m]}")
        lines.append(f"{m.upper()}_LOADED = True")
        files[f"{pkg}/{m}.py"] = "\n".join(lines) + "\n"
    files[f"{pkg}/legacy.py"] = f"\"\"\"Old values, no longer imported.\"\"\"\n{name} = {vals[4]}\n"
    files[f"{pkg}/client.py"] = (f"\"\"\"Client. {name} defaults to {vals[0]} unless a later module sets it.\"\"\"\n"
                                 f"from {pkg}.{chain[-1]} import {name}\n\n\ndef plan(jobs):\n"
                                 f"    return [jobs[i:i + {name}] for i in range(0, len(jobs), {name})]\n")
    decoys = sorted((set(assigned.values()) | {vals[0], vals[4]}) - {answer})
    return {"prompt": f"What value of {name} does {pkg}/client.py end up using? Answer with the number.",
            "files": files, "answer": str(answer), "decoys": [str(v) for v in decoys],
            "check": {"module": f"{pkg}.client", "name": name}}


def scene(row: dict) -> dict:
    """The repo, prompt and grade of one row."""
    rng = random.Random(f"{_KEY}:{VERSION}:{row['seed']}:{row['item']}:{row['attempt']}")
    pkg = rng.choice(PACKAGES)
    kind = row["kind"]
    if kind in BUGGY:
        return _fix(rng, pkg, kind == "trace")
    if kind == "edit":
        return _edit(rng, pkg)
    if kind in ("rename", "move"):
        return _refactor(rng, pkg, kind == "move")
    return {"config": lambda: _config(rng), "locate": lambda: _locate(rng, pkg),
            "constant": lambda: _constant(rng, pkg)}[kind]()


def _scene(row: dict) -> dict:
    while True:
        try:
            return scene(row)
        except _Redraw:
            row["attempt"] += 1


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, kinds in equal turn."""
    kinds = sorted(KINDS)
    out = []
    for i in range(count):
        row = {"item": i, "seed": seed, "kind": kinds[i % len(kinds)], "attempt": 0}
        _scene(row)
        out.append(row)
    return out


def answers(row: dict) -> tuple[str, list[str]]:
    """A read case's answer and the values in its repo that are not the answer."""
    s = _scene(dict(row))
    return s["answer"], s["decoys"]


def case_id(row: dict) -> str:
    return f"agent-{KINDS[row['kind']]}-synth-{row['item']:04d}"


def case_of(row: dict) -> dict:
    s = _scene(dict(row))
    cid = case_id(row)
    att = provenance(sys.modules[__name__], row["item"],
                     "a seeded repo with its task, graded by hidden tests or the answer it computes")
    att.update(version=VERSION, seed=row["seed"], kind=row["kind"])
    read = "answer" in s
    return {"id": cid, "modality": LANE, "prompt": s["prompt"],
            "params": {"repo": f"repos/{cid}", "tools": list(READ_TOOLS if read else EDIT_TOOLS),
                       "max_steps": MAX_STEPS[row["kind"]]},
            "assert": {"answer": [s["answer"]]} if read else {"hidden": True},
            "attribution": att}


def convert(row: dict) -> Imported:
    s = _scene(dict(row))
    cid = case_id(row)
    files = [(f"repos/{cid}/repo/{rel}", text.encode("utf-8")) for rel, text in sorted(s["files"].items())]
    if "hidden" in s:
        files.append((f"repos/{cid}/hidden/{HIDDEN}", s["hidden"].encode("utf-8")))
        files += [(f"repos/{cid}/solution/{rel}", text.encode("utf-8"))
                  for rel, text in sorted(s["solution"].items())]
    return Imported(case_of(row), files=tuple(files))


def _bundle(case):
    return case.source.parent / case.params["repo"]


def _reference(case):
    """The right answer of a read case, or the solution files of an edit case."""
    if case.assertions.get("answer"):
        return str(case.assertions["answer"][0])
    sol = _bundle(case) / "solution"
    return {f.relative_to(sol).as_posix(): f.read_text(encoding="utf-8") for f in sorted(sol.rglob("*.py"))}


RESPONDERS = {"reference": _reference,
              "untouched": lambda case: {} if case.assertions.get("hidden") else "I could not tell."}


def passes(case, answer) -> bool:
    """Grade an answer (text) or a set of written files (dict) the way the agent lane does."""
    from evals import sandbox
    box = sandbox.Sandbox.create(_bundle(case) / "repo")
    try:
        if isinstance(answer, dict):
            for rel, text in answer.items():
                box.write_file(rel, text)
            return sandbox.grade(box, _bundle(case) / "hidden", None, "")["passed"]
        return sandbox.grade(box, None, case.assertions["answer"], answer)["passed"]
    finally:
        box.cleanup()
