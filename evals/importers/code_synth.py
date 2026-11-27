"""Generated code cases: seeded specs with a reference, a wrong variant and checks computed by the reference. #603."""
from __future__ import annotations

import hashlib
import random
import sys

from evals.importers import Imported, provenance

LANE = "code"
VERSION = "1"
SEED = 603
COUNT = 880
DATE = "2026-11-27"
SOURCE = f"generated:evals.importers.code_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated code cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/code_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "code-synth"
CHECKS = 6
ATTEMPTS = 120
#: The most cases one algorithm template may fill, so no one problem shape dominates the set.
TEMPLATE_CAP = 70
NAMES = ["solve", "transform", "process", "compute", "apply_rules", "reduce_data", "run_pipeline"]
TRANSFORM = ("a seeded spec; checks are the reference's answers on seeded inputs; the example in the "
             "prompt is a further input; the wrong variant must fail at least one check")


def _step(text: str, code: str) -> tuple[str, str]:
    return text, code


def _plain(t: str, c: str):
    return lambda r: _step(t, c)


def _pick(r, options):
    return r.choice(options)


def _keep_gt(r):
    k = r.randint(-3, 8)
    return _step(f"keep only the values greater than {k}", f"xs = [x for x in xs if x > {k}]")


def _drop_mult(r):
    m = _pick(r, [2, 3, 4, 5, 7])
    return _step(f"remove every value that is a multiple of {m} (0 is a multiple of everything)",
                 f"xs = [x for x in xs if x % {m} != 0]")


def _add(r):
    c = r.choice([-9, -5, -3, -1, 2, 4, 6, 9])
    return _step(f"add {c} to every value", f"xs = [x + {c} for x in xs]")


def _mul(r):
    c = r.choice([-2, -1, 2, 3, 5])
    return _step(f"multiply every value by {c}", f"xs = [x * {c} for x in xs]")


def _mod(r):
    m = r.randint(3, 9)
    return _step(f"replace every value with its remainder after division by {m}, as Python's % gives it "
                 f"(never negative)", f"xs = [x % {m} for x in xs]")


def _trunc(r):
    d = r.choice([2, 3, 4])
    return _step(f"divide every value by {d} with integer division that rounds toward zero "
                 f"(so -7 divided by {d} gives {int(-7 / d)})", f"xs = [int(x / {d}) for x in xs]")


def _floor(r):
    d = r.choice([2, 3, 4])
    return _step(f"divide every value by {d} with floor division (so -7 divided by {d} gives {-7 // d})",
                 f"xs = [x // {d} for x in xs]")


def _first(r):
    k = r.randint(2, 6)
    return _step(f"keep only the first {k} values (all of them if there are fewer)", f"xs = xs[:{k}]")


def _drop(r):
    k = r.randint(1, 3)
    return _step(f"drop the first {k} values (an empty list if there are fewer)", f"xs = xs[{k}:]")


def _last(r):
    k = r.randint(2, 5)
    return _step(f"keep only the last {k} values, in their order (all of them if there are fewer)",
                 f"xs = xs[-{k}:]")


def _rotate(r):
    k = r.randint(1, 9)
    return _step(f"rotate the list left by {k} positions, wrapping around (an empty list stays empty)",
                 f"if xs:\n        k = {k} % len(xs)\n        xs = xs[k:] + xs[:k]")


def _every(r):
    n = r.choice([2, 3])
    return _step(f"keep the values at indices 0, {n}, {2 * n}, and so on", f"xs = xs[::{n}]")


def _clamp(r):
    lo = r.randint(-5, 1)
    hi = lo + r.randint(3, 9)
    return _step(f"clamp every value into the range {lo} to {hi}, both inclusive",
                 f"xs = [min({hi}, max({lo}, x)) for x in xs]")


def _window(r):
    k = r.randint(2, 4)
    return _step(f"replace every value with the largest of itself and the up to {k - 1} values before it",
                 f"xs = [max(xs[max(0, i - {k - 1}):i + 1]) for i in range(len(xs))]")


INT_STEPS = [
    _keep_gt, _drop_mult, _add, _mul, _mod, _trunc, _floor, _first, _drop, _last, _rotate, _every, _clamp,
    _window,
    _plain("remove every negative value", "xs = [x for x in xs if x >= 0]"),
    _plain("keep only the even values", "xs = [x for x in xs if x % 2 == 0]"),
    _plain("replace every value with its square", "xs = [x * x for x in xs]"),
    _plain("replace every value with its absolute value", "xs = [abs(x) for x in xs]"),
    _plain("remove duplicates, keeping the first occurrence of each value",
           "xs = list(dict.fromkeys(xs))"),
    _plain("remove duplicates, keeping only the last occurrence of each value, in the order those last "
           "occurrences appear", "xs = list(dict.fromkeys(reversed(xs)))[::-1]"),
    _plain("sort ascending", "xs = sorted(xs)"),
    _plain("sort descending", "xs = sorted(xs, reverse=True)"),
    _plain("reverse the list", "xs = xs[::-1]"),
    _plain("sort by absolute value, values with equal absolute value keeping their current relative order",
           "xs = sorted(xs, key=abs)"),
    _plain("replace the list with its running sums (the value at index i becomes the sum of the values at "
           "indices 0 to i)", "xs = [sum(xs[:i + 1]) for i in range(len(xs))]"),
    _plain("replace the list with the differences between consecutive values, later minus earlier (a list "
           "with fewer than two values becomes empty)", "xs = [b - a for a, b in zip(xs, xs[1:])]"),
    _plain("replace every value with the largest value seen so far",
           "xs = [max(xs[:i + 1]) for i in range(len(xs))]"),
    _plain("swap each adjacent pair (indices 0 and 1, then 2 and 3, and so on); an unpaired last value stays",
           "xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]"),
    _plain("collapse each run of equal adjacent values into one value",
           "xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]"),
    _plain("replace the list with the sums of non-overlapping consecutive pairs; a lone final value stays as "
           "it is", "xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]"),
]

INT_ENDS = [
    ("Return the resulting list.", "return xs"),
    ("Return the sum of the values (0 for an empty list).", "return sum(xs)"),
    ("Return the largest value, or -1 for an empty list.", "return max(xs) if xs else -1"),
    ("Return how many distinct values there are.", "return len(set(xs))"),
    ("Return the second largest distinct value, or None if there are fewer than two distinct values.",
     "d = sorted(set(xs))\n    return d[-2] if len(d) > 1 else None"),
    ("Return the lower median: the value at index (n - 1) // 2 of the sorted list, or 0 for an empty list.",
     "return sorted(xs)[(len(xs) - 1) // 2] if xs else 0"),
    ("Return the index of the first occurrence of the largest value, or -1 for an empty list.",
     "return xs.index(max(xs)) if xs else -1"),
    ("Return True if the values are strictly increasing (an empty list or a single value counts), else False.",
     "return all(a < b for a, b in zip(xs, xs[1:]))"),
    ("Return a list of the two smallest values in ascending order (fewer if there are fewer).",
     "return sorted(xs)[:2]"),
]


def _vowel_free(r):
    return _step("remove every vowel (a, e, i, o, u, either case)",
                 "s = ''.join(c for c in s if c.lower() not in 'aeiou')")


def _caesar(r):
    k = r.randint(1, 12)
    return _step(f"shift every letter forward by {k} places in the alphabet, wrapping from z to a and keeping "
                 f"its case; other characters are unchanged",
                 "s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + %d) %% 26 + "
                 "ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)" % k)


def _replace(r):
    a, b = r.sample("abcdeilnorst", 2)
    return _step(f"replace every '{a}' with '{b}' (lowercase only)", f"s = s.replace('{a}', '{b}')")


def _pad(r):
    k = r.randint(5, 9)
    return _step(f"cut the text to at most {k} characters, then pad it on the right with '.' up to {k} "
                 f"characters", f"s = s[:{k}].ljust({k}, '.')")


def _wordcut(r):
    k = r.randint(2, 4)
    return _step(f"keep only the first {k} whitespace-separated words, joined by single spaces",
                 f"s = ' '.join(s.split()[:{k}])")


STR_STEPS = [
    _vowel_free, _caesar, _replace, _pad, _wordcut,
    _plain("convert to lowercase", "s = s.lower()"),
    _plain("convert to uppercase", "s = s.upper()"),
    _plain("collapse every run of the same character into one character",
           "s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])"),
    _plain("remove every digit", "s = ''.join(c for c in s if not c.isdigit())"),
    _plain("swap the case of every letter", "s = s.swapcase()"),
    _plain("reverse the order of the whitespace-separated words and join them with single spaces",
           "s = ' '.join(reversed(s.split()))"),
    _plain("reverse the characters of every whitespace-separated word, joining the words with single spaces",
           "s = ' '.join(w[::-1] for w in s.split())"),
    _plain("capitalize every whitespace-separated word (first letter upper case, the rest lower case), "
           "joining the words with single spaces", "s = ' '.join(w.capitalize() for w in s.split())"),
    _plain("keep only the first occurrence of each character", "s = ''.join(dict.fromkeys(s))"),
    _plain("replace runs of whitespace with a single space and strip both ends", "s = ' '.join(s.split())"),
    _plain("replace every maximal run of digits with the number of digits in it",
           "import re\n    s = re.sub(r'\\d+', lambda m: str(len(m.group())), s)"),
    _plain("sort the characters in ascending code point order", "s = ''.join(sorted(s))"),
    _plain("run-length encode: every run of one character becomes its length then the character "
           "(so 'aaab' becomes '3a1b')",
           "import itertools\n    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))"),
]

STR_ENDS = [
    ("Return the resulting string.", "return s"),
    ("Return how many characters it has.", "return len(s)"),
    ("Return the longest whitespace-separated word, the first one if several tie, or '' if there are none.",
     "w = s.split()\n    return max(w, key=len) if w else ''"),
    ("Return True if it reads the same backwards when only letters and digits are considered and case is "
     "ignored, else False.",
     "t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]"),
    ("Return the most frequent character, the smallest by code point if several tie, or '' for an empty "
     "string.", "return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''"),
    ("Return the number of words (whitespace-separated).", "return len(s.split())"),
]

WORDS = ["Quick brown fox", "  jumps   over the  lazy dog ", "Zebra 42 crossing 7", "aabbbcccc", "Level", "Rotor 99",
         "Hello, World", "mississippi river", "A man a plan a canal Panama", "abc123xyz", "  ", "", "x",
         "The 3 little pigs 33", "queue QUEUE", "noon", "Data-driven 2025", "eeeee fff", "Programming in Python",
         "hELLo WoRLD", "tab\tseparated  words", "zz yy xx", "Ünïcode ok", "12345", "banana bandana"]


def _int_inputs(r: random.Random) -> list[tuple]:
    out = [([],), ([r.randint(-9, 9)],)]
    while len(out) < CHECKS + 1:
        out.append(([r.randint(-12, 25) for _ in range(r.randint(3, 9))],))
    return out


def _str_inputs(r: random.Random) -> list[tuple]:
    pool = r.sample(WORDS, CHECKS)
    pool.append("".join(r.choice("abcxyzABC 012,.") for _ in range(r.randint(8, 16))))
    return [(w,) for w in pool]


def _source(fn: str, arg: str, steps, end: str) -> str:
    body = "\n".join("    " + code for _, code in steps)
    tail = "    " + end
    return f"def {fn}({arg}):\n{body}\n{tail}\n" if steps else f"def {fn}({arg}):\n{tail}\n"


def _pipeline(r: random.Random, kind: str) -> dict:
    steps_pool, ends, arg = (INT_STEPS, INT_ENDS, "xs") if kind == "ints" else (STR_STEPS, STR_ENDS, "s")
    n = r.choice([6, 8, 8, 10, 12])
    chosen, prev = [], None
    while len(chosen) < n:
        make = r.choice(steps_pool)
        if make is not prev:
            chosen.append(make(r))
            prev = make
    end = r.choice(ends)
    fn = r.choice(NAMES)
    noun = "a list of integers" if kind == "ints" else "a string"
    listing = "\n".join(f"{i}. {t[0].upper() + t[1:]}." for i, (t, _) in enumerate(chosen, 1))
    text = (f"Write a Python function `{fn}({arg})` that takes {noun} and applies these steps in order, each "
            f"to the result of the one before:\n{listing}\nThen: {end[0]}")
    wrong_steps, wrong_end = list(chosen), end
    how = r.choice(["drop", "swap", "end"])
    if how == "swap":
        i = r.randrange(n - 1)
        wrong_steps[i], wrong_steps[i + 1] = wrong_steps[i + 1], wrong_steps[i]
    elif how == "drop":
        wrong_steps.pop(r.randrange(n))
    else:
        wrong_end = r.choice([e for e in ends if e != end])
    return {"fn": fn, "text": text, "ref": _source(fn, arg, chosen, end[1]),
            "wrong": _source(fn, arg, wrong_steps, wrong_end[1]),
            "inputs": (_int_inputs if kind == "ints" else _str_inputs)(r), "stratum": f"{kind}-{n}-steps"}


PEOPLE = ["Ada", "Bram", "Cleo", "Dara", "Eli", "Fay", "Gus", "Hugo", "Iris", "Jon", "Kira", "Leo", "Mina",
         "Nico", "Olga", "Pia", "Quin", "Rhea", "Sol", "Tess", "Uma", "Vic", "Wren", "Xan", "Yara", "Zed"]
DEPTS = ["ops", "dev", "qa", "sales", "hr", "legal"]


def _rows(r: random.Random) -> list[tuple]:
    out = []
    for _ in range(CHECKS + 1):
        names = r.sample(PEOPLE, r.randint(4, 8))
        depts = r.sample(DEPTS, 3)
        scores = [r.choice([50, 60, 70, 70, 80, 80, 90, 95]) for _ in names]
        out.append(([(n, r.choice(depts), s) for n, s in zip(names, scores)],))
    return out


def _records(r: random.Random) -> dict:
    fn = r.choice(NAMES)
    k, t = r.randint(2, 4), r.choice([60, 70, 80])
    kinds = {
        "topk": (f"return the names of the {k} highest scores as a list, highest score first, equal scores "
                 f"ordered by name ascending; if there are fewer than {k} rows return every name",
                 f"return [n for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]))][:{k}]",
                 f"return [n for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]), reverse=True)][:{k}]"),
        "above": ("return the sorted list of names whose score is strictly above the average score of their "
                  "own department",
                  "tot = {}\n    for n, d, s in rows:\n        a = tot.setdefault(d, [0, 0])\n"
                  "        a[0] += s\n        a[1] += 1\n"
                  "    return sorted(n for n, d, s in rows if s * tot[d][1] > tot[d][0])",
                  "tot = {}\n    for n, d, s in rows:\n        a = tot.setdefault(d, [0, 0])\n"
                  "        a[0] += s\n        a[1] += 1\n"
                  "    return sorted(n for n, d, s in rows if s * tot[d][1] >= tot[d][0])"),
        "best": ("return the department with the highest total score, the alphabetically first one if "
                 "several tie, or None if there are no rows",
                 "t = {}\n    for n, d, s in rows:\n        t[d] = t.get(d, 0) + s\n"
                 "    return min(t, key=lambda d: (-t[d], d)) if t else None",
                 "t = {}\n    for n, d, s in rows:\n        t[d] = t.get(d, 0) + s\n"
                 "    return max(t, key=lambda d: (t[d], d)) if t else None"),
        "rank": ("return a list of (name, rank) tuples ordered by rank then name; rank is competition style: "
                 "the highest score is rank 1, equal scores share a rank, and the rank after a tie skips "
                 "(scores 90, 80, 80, 70 rank 1, 2, 2, 4)",
                 "return sorted(((n, 1 + sum(1 for x in rows if x[2] > s)) for n, d, s in rows), "
                 "key=lambda p: (p[1], p[0]))",
                 "return sorted(((n, 1 + len({x[2] for x in rows if x[2] > s})) for n, d, s in rows), "
                 "key=lambda p: (p[1], p[0]))"),
        "count": (f"return a dict mapping each department that has at least one score of {t} or more to how "
                  f"many such scores it has",
                  f"c = {{}}\n    for n, d, s in rows:\n        if s >= {t}:\n            c[d] = c.get(d, 0) + 1\n"
                  f"    return c",
                  f"c = {{}}\n    for n, d, s in rows:\n        if s > {t}:\n            c[d] = c.get(d, 0) + 1\n"
                  f"    return c"),
        "groups": ("return a dict mapping each department to the list of its names sorted by score "
                   "descending, equal scores ordered by name ascending",
                   "g = {}\n    for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0])):\n"
                   "        g.setdefault(d, []).append(n)\n    return g",
                   "g = {}\n    for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]), reverse=True):\n"
                   "        g.setdefault(d, []).append(n)\n    return g"),
    }
    kind = r.choice(sorted(kinds))
    what, ref, wrong = kinds[kind]
    text = (f"Write a Python function `{fn}(rows)`. `rows` is a list of (name, department, score) tuples with "
            f"integer scores and unique names, possibly empty. Given them, {what}.")
    dept, mark = r.choice(["department", "team", "region"]), r.choice(["score", "rating", "mark"])
    text = text.replace("department", dept).replace("score", mark)
    return {"fn": fn, "text": text, "ref": f"def {fn}(rows):\n    {ref}\n", "wrong": f"def {fn}(rows):\n    {wrong}\n",
            "inputs": _rows(r), "stratum": f"records-{kind}"}


def _grid(r: random.Random, blocked: float = 0.25) -> list[str]:
    h, w = r.randint(2, 5), r.randint(2, 5)
    g = [["#" if r.random() < blocked else "." for _ in range(w)] for _ in range(h)]
    g[0][0] = g[-1][-1] = "."
    return ["".join(row) for row in g]


def _algo_ways(r):
    sizes = sorted(r.sample(range(1, 7), r.choice([2, 3])))
    mod = r.choice([1000, 10007, 1_000_000_007])
    bad = sorted(set(sizes[:-1] + [sizes[-1] + 1]))
    body = ("w = [1] + [0] * n\n    for i in range(1, n + 1):\n        w[i] = sum(w[i - s] for s in %s if i >= s) "
            "%% %d\n    return w[n]\n")
    return {"fn": "ways", "text": (f"Write a Python function `ways(n)` that returns the number of ordered ways to "
                                   f"climb exactly n steps when each move climbs one of {sizes} steps, "
                                   f"modulo {mod}. There is one way to climb 0 steps."),
            "ref": "def ways(n):\n    " + body % (sizes, mod), "wrong": "def ways(n):\n    " + body % (bad, mod),
            "inputs": [(n,) for n in (0, 1, 3, 7, 12, 25, 40, 19)], "stratum": "algo-ways"}


def _algo_coins(r):
    u = r.randint(1, 4)
    bad = u + 1
    body = ("INF = float('inf')\n    best = [0] + [INF] * amount\n    for c in coins:\n"
            "        nxt = best[:]\n        for a in range(amount + 1):\n"
            "            for j in range(1, %d + 1):\n"
            "                if a >= j * c and best[a - j * c] + j < nxt[a]:\n"
            "                    nxt[a] = best[a - j * c] + j\n        best = nxt\n"
            "    return best[amount] if best[amount] != INF else -1\n")
    rows = []
    for _ in range(CHECKS + 1):
        coins = r.sample([1, 2, 3, 4, 5, 7, 10], r.randint(2, 4))
        rows.append((coins, r.randint(0, 25)))
    return {"fn": "min_coins", "text": (f"Write a Python function `min_coins(coins, amount)` that returns the fewest "
                                        f"coins that sum to exactly `amount`, where `coins` lists distinct "
                                        f"denominations and each denomination may be used at most {u} time"
                                        f"{'s' if u > 1 else ''}. Return -1 if the amount cannot be made; an "
                                        f"amount of 0 needs 0 coins."),
            "ref": "def min_coins(coins, amount):\n    " + body % u, "wrong": "def min_coins(coins, amount):\n    " + body % bad,
            "inputs": rows, "stratum": "algo-coins"}


def _algo_chain(r):
    d = r.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6])
    body = ("best = {}\n    for x in xs:\n        best[x] = max(best.get(x, 0), best.get(x - (%d), 0) + 1)\n"
            "    return max(best.values()) if best else 0\n")
    return {"fn": "longest_chain", "text": (f"Write a Python function `longest_chain(xs)` that returns the length of the "
                                            f"longest subsequence of the list `xs` (elements kept in their original "
                                            f"order, not necessarily adjacent) in which every element is exactly {d} "
                                            f"more than the one before it. An empty list gives 0."),
            "ref": "def longest_chain(xs):\n    " + body % d, "wrong": "def longest_chain(xs):\n    " + body % (-d),
            "inputs": [([r.randint(-4, 8) for _ in range(r.randint(0, 11))],) for _ in range(CHECKS + 1)],
            "stratum": "algo-chain"}


def _algo_subsets(r):
    mod = r.choice([5, 7, 11, 13, 97, 1_000_003])
    body = ("ways = {0: 1}\n    for x in nums:\n        for s, c in list(ways.items()):\n"
            "            ways[s + x] = ways.get(s + x, 0) + c\n    return ways.get(target, 0) %% %d\n")
    rows = [([r.randint(1, 6) for _ in range(r.randint(3, 12))], r.randint(3, 14)) for _ in range(CHECKS + 1)]
    return {"fn": "count_subsets", "text": (f"Write a Python function `count_subsets(nums, target)` that returns, "
                                            f"modulo {mod}, how many subsets of positions of `nums` sum to exactly "
                                            f"`target`. Two equal values at different positions count as different "
                                            f"subsets; the empty subset has sum 0."),
            "ref": "def count_subsets(nums, target):\n    " + body % mod,
            "wrong": "def count_subsets(nums, target):\n    " + body.replace("for x in nums", "for x in set(nums)") % mod,
            "inputs": rows, "stratum": "algo-subsets"}


def _algo_paths(r):
    diag = r.random() < 0.5
    mod = r.choice([100, 997, 1000, 10007])
    moves = "[(0, 1), (1, 0), (1, 1)]" if diag else "[(0, 1), (1, 0)]"
    body = ("h, w = len(grid), len(grid[0])\n    n = [[0] * w for _ in range(h)]\n"
            "    for i in range(h):\n        for j in range(w):\n"
            "            if grid[i][j] == '#':\n                continue\n"
            "            n[i][j] = 1 if i == j == 0 else sum(n[i - a][j - b] for a, b in %s "
            "if i >= a and j >= b) %% %d\n    return n[-1][-1]\n")
    other = "[(0, 1), (1, 0)]" if diag else "[(0, 1), (1, 0), (1, 1)]"
    moves_text = "right, down or diagonally down-right" if diag else "right or down"
    return {"fn": "count_paths", "text": (f"Write a Python function `count_paths(grid)` where `grid` is a non-empty list "
                                          f"of equal-length strings of '.' (open) and '#' (blocked). Return the number "
                                          f"of ways to go from the top-left cell to the bottom-right cell moving one "
                                          f"cell {moves_text} per move, never entering a '#' cell, modulo {mod}. The "
                                          f"start and end cells are open."),
            "ref": "def count_paths(grid):\n    " + body % (moves, mod),
            "wrong": "def count_paths(grid):\n    " + body % (other, mod),
            "inputs": [(_grid(r),) for _ in range(CHECKS + 1)], "stratum": "algo-paths"}


def _algo_edit(r):
    ci, cd, cs = r.randint(1, 3), r.randint(1, 3), r.randint(1, 4)
    body = ("d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]\n    for i in range(len(a) + 1):\n"
            "        for j in range(len(b) + 1):\n            if i == 0 or j == 0:\n"
            "                d[i][j] = j * %d if i == 0 else i * %d\n                continue\n"
            "            d[i][j] = min(d[i - 1][j] + %d, d[i][j - 1] + %d, "
            "d[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else %d))\n    return d[-1][-1]\n")
    words = ["kitten", "sitting", "flaw", "lawn", "", "abc", "cab", "plan", "plane", "sunday", "saturday", "ab"]
    rows = [tuple(r.sample(words, 2)) for _ in range(CHECKS + 1)]
    return {"fn": "edit_cost", "text": (f"Write a Python function `edit_cost(a, b)` returning the minimum total cost of "
                                        f"turning string `a` into string `b` when inserting a character costs {ci}, "
                                        f"deleting one costs {cd}, replacing one character with a different one costs "
                                        f"{cs}, and keeping a matching character is free."),
            "ref": "def edit_cost(a, b):\n    " + body % (ci, cd, cd, ci, cs),
            "wrong": "def edit_cost(a, b):\n    " + body % (cd, ci, ci, cd, cs),
            "inputs": rows, "stratum": "algo-edit"}


def _algo_josephus(r):
    k = r.randint(2, 9)
    body = ("people = list(range(1, n + 1))\n    i, out = 0, []\n    while people:\n"
            "        i = (i + %d) %% len(people)\n        out.append(people.pop(i))\n    return out\n")
    ref, wrong = body % (k - 1), body % k
    return {"fn": "elimination_order", "text": (f"Write a Python function `elimination_order(n)`: n people numbered 1 to n "
                                                f"stand in a circle. Counting starts at person 1 as count 1; the "
                                                f"person at count {k} is removed, and counting resumes with the next "
                                                f"remaining person as count 1. Return the list of people in the "
                                                f"order they are removed, for n >= 0."),
            "ref": "def elimination_order(n):\n    " + ref, "wrong": "def elimination_order(n):\n    " + wrong,
            "inputs": [(n,) for n in (0, 1, 2, 5, 7, 10, 13, 8)], "stratum": "algo-josephus"}


def _algo_robin(r):
    q = r.randint(2, 6)
    body = ("left = list(bursts)\n    done = [0] * len(bursts)\n    queue = list(range(len(bursts)))\n"
            "    t = 0\n    while queue:\n        i = queue.pop(0)\n        run = min(%d, left[i])\n"
            "        t += run\n        left[i] -= run\n        if left[i] > 0:\n            queue.append(i)\n"
            "        else:\n            done[i] = t\n    return done\n")
    rows = [([r.randint(1, 9) for _ in range(r.randint(0, 5))],) for _ in range(CHECKS + 1)]
    return {"fn": "finish_times", "text": (f"Write a Python function `finish_times(bursts)`. Processes 0..n-1 all arrive at "
                                           f"time 0 and need `bursts[i]` units of CPU. A round-robin scheduler gives "
                                           f"the process at the front of the queue up to {q} units, then, if it is "
                                           f"not finished, puts it at the back. Return the list of finishing times "
                                           f"indexed by process."),
            "ref": "def finish_times(bursts):\n    " + body % q, "wrong": "def finish_times(bursts):\n    " + body % (q + 1),
            "inputs": rows, "stratum": "algo-roundrobin"}


def _algo_cache(r):
    c = r.randint(2, 6)
    lru = r.random() < 0.5
    touch = "            cache.remove(x)\n            cache.append(x)\n" if lru else "            pass\n"
    body = ("cache, hits = [], 0\n    for x in seq:\n        if x in cache:\n            hits += 1\n%s"
            "        else:\n            if len(cache) == %d:\n                cache.pop(0)\n"
            "            cache.append(x)\n    return hits\n")
    policy = ("the least recently used item (a hit refreshes an item)" if lru
              else "the item that has been in the cache longest (a hit does not refresh it)")
    return {"fn": "cache_hits", "text": (f"Write a Python function `cache_hits(seq)` that simulates a cache holding at "
                                         f"most {c} items over the sequence of requests `seq` and returns the number "
                                         f"of requests that were already in the cache. A missing item is inserted; if "
                                         f"the cache is full, {policy} is evicted first."),
            "ref": "def cache_hits(seq):\n    " + body % (touch, c),
            "wrong": "def cache_hits(seq):\n    " + body % (("            pass\n" if lru else
                                                              "            cache.remove(x)\n            cache.append(x)\n"), c),
            "inputs": [([r.randint(1, 6) for _ in range(r.randint(0, 14))],) for _ in range(CHECKS + 1)],
            "stratum": "algo-cache"}


def _algo_merge(r):
    g = r.randint(0, 6)
    body = ("out = []\n    for s, e in sorted(spans):\n        if out and s <= out[-1][1] + %d:\n"
            "            out[-1][1] = max(out[-1][1], e)\n        else:\n            out.append([s, e])\n"
            "    return out\n")
    rows = []
    for _ in range(CHECKS + 1):
        spans = []
        for _ in range(r.randint(0, 7)):
            s = r.randint(0, 20)
            spans.append((s, s + r.randint(0, 4)))
        rows.append((spans,))
    return {"fn": "merge_spans", "text": (f"Write a Python function `merge_spans(spans)` where `spans` is a list of "
                                          f"(start, end) integer pairs with start <= end, in any order. Merge spans "
                                          f"that overlap or whose gap is at most {g} (the next start is at most the "
                                          f"current end plus {g}). Return the merged spans as a list of [start, end] "
                                          f"lists sorted by start."),
            "ref": "def merge_spans(spans):\n    " + body % g,
            "wrong": "def merge_spans(spans):\n    " + body % (g + 1), "inputs": rows, "stratum": "algo-merge"}


def _algo_union(r):
    def clock(m):
        return f"{m // 60:02d}:{m % 60:02d}"
    rows = []
    for _ in range(CHECKS + 1):
        rg = []
        for _ in range(r.randint(0, 5)):
            s = r.randint(0, 22 * 60)
            rg.append(f"{clock(s)}-{clock(min(s + r.randint(1, 150), 1439))}")
        rows.append((rg,))
    body = ("spans = sorted((int(a[:2]) * 60 + int(a[3:5]), int(a[6:8]) * 60 + int(a[9:11])) for a in ranges)\n"
            "    total, end = 0, -1\n    for s, e in spans:\n        s = max(s, end)\n        if e > s:\n"
            "            total += e - s\n        end = max(end, e)\n    return total\n")
    wrong = "return sum(int(a[6:8]) * 60 + int(a[9:11]) - int(a[:2]) * 60 - int(a[3:5]) for a in ranges)\n"
    return {"fn": "minutes_covered", "text": ("Write a Python function `minutes_covered(ranges)` where `ranges` is a list of "
                                              "strings like '09:30-10:15' (24-hour HH:MM-HH:MM, same day, start before "
                                              "end). Return the total number of minutes covered by at least one range; "
                                              "overlapping time is counted once."),
            "ref": "def minutes_covered(ranges):\n    " + body, "wrong": "def minutes_covered(ranges):\n    " + wrong,
            "inputs": rows, "stratum": "algo-union"}


def _algo_stack(r):
    ops = r.sample(["dup", "swap", "add", "mul", "sub", "drop", "over"], 4)
    code = {"dup": "if st:\n                st.append(st[-1])", "drop": "if st:\n                st.pop()",
            "swap": "if len(st) > 1:\n                st[-1], st[-2] = st[-2], st[-1]",
            "over": "if len(st) > 1:\n                st.append(st[-2])",
            "add": "if len(st) > 1:\n                b = st.pop()\n                st[-1] += b",
            "mul": "if len(st) > 1:\n                b = st.pop()\n                st[-1] *= b",
            "sub": "if len(st) > 1:\n                b = st.pop()\n                st[-1] -= b"}
    words = {"dup": "dup copies the top value onto the stack", "drop": "drop removes the top value",
             "swap": "swap exchanges the top two values", "over": "over pushes a copy of the second value from the top",
             "add": "add pops two values and pushes their sum", "mul": "mul pops two values and pushes their product",
             "sub": "sub pops b then a and pushes a - b, so the value pushed first is a"}
    def src(ops_used):
        chain = "".join(f"        {'if' if i == 0 else 'elif'} t == '{o}':\n            {code[o]}\n"
                        for i, o in enumerate(ops_used))
        return (f"def run_program(tokens):\n    st = []\n    for t in tokens:\n        if isinstance(t, int):\n"
                f"            st.append(t)\n{chain}    return st\n")
    wrong = src(ops).replace("st[-1] -= b", "st[-1] = b - st[-1]")
    wrong_src = wrong if "sub" in ops else src(ops).replace("st.append(t)", "st.append(abs(t))")
    rows = [([r.choice([r.randint(-3, 9)] * 2 + ops) for _ in range(r.randint(2, 9))],) for _ in range(CHECKS + 1)]
    return {"fn": "run_program", "text": ("Write a Python function `run_program(tokens)` for a small stack machine. "
                                         "`tokens` is a list whose items are ints (pushed onto the stack) or the "
                                         f"strings {', '.join(repr(o) for o in ops)}: " + "; ".join(words[o] for o in ops) +
                                         ". An operation that needs more values than the stack has does nothing. "
                                         "Return the final stack as a list, bottom first."),
            "ref": src(ops), "wrong": wrong_src, "inputs": rows, "stratum": "algo-stack"}


def _algo_brackets(r):
    pairs = r.choice(["()[]", "()[]{}", "()<>", "[]{}", "<>[]", "()[]<>"])
    op, cl = pairs[0::2], pairs[1::2]
    body = ("stack = []\n    for i, c in enumerate(s):\n        if c in %r:\n            stack.append((c, i))\n"
            "        elif c in %r:\n            if not stack or %r.index(stack[-1][0]) != %r.index(c):\n"
            "                return i\n            stack.pop()\n    return stack[%s][1] if stack else -1\n")
    wrong_body = body.replace("return stack[%s][1]", "return stack[-1][1]")
    rows = []
    for _ in range(CHECKS + 1):
        rows.append(("".join(r.choice(op * 3 + cl + "ab") for _ in range(r.randint(0, 12))),))
    return {"fn": "first_bracket_error", "text": (f"Write a Python function `first_bracket_error(s)` for a string `s` "
                                                  f"in which only the brackets {' '.join(op[i] + cl[i] for i in range(len(op)))}"
                                                  f" matter and every other character is ignored. Return the index of "
                                                  f"the first closing bracket that has no matching opener of the same "
                                                  f"kind on top of the stack; if there is none, return the index of "
                                                  f"the earliest opening bracket that is never closed; otherwise -1."),
            "ref": "def first_bracket_error(s):\n    " + body % (op, cl, op, cl, "0"),
            "wrong": "def first_bracket_error(s):\n    " + wrong_body % (op, cl, op, cl),
            "inputs": rows, "stratum": "algo-brackets"}


def _algo_rotate(r):
    k = r.randint(1, 11)
    body = ("for _ in range(%d %% 4):\n        m = [list(row) for row in zip(*m[::-1])]\n    return m\n")
    rows = [([[r.randint(0, 9) for _ in range(w)] for _ in range(h)],) for h, w in
            [(r.randint(1, 4), r.randint(1, 4)) for _ in range(CHECKS + 1)]]
    return {"fn": "rotate_grid", "text": (f"Write a Python function `rotate_grid(m)` that rotates the rectangular list-of-"
                                          f"lists `m` by 90 degrees clockwise {k} times and returns the new list of "
                                          f"lists (a 2x3 grid becomes 3x2 after one turn; `m` itself must not change)."),
            "ref": "def rotate_grid(m):\n    " + body % k,
            "wrong": "def rotate_grid(m):\n    " + body.replace("zip(*m[::-1])", "zip(*m)").replace(
                "for row in zip(*m)]", "for row in zip(*m)][::-1]") % k,
            "inputs": rows, "stratum": "algo-rotate"}


def _algo_business(r):
    import datetime
    hol = sorted(r.sample(["2026-12-24", "2026-12-25", "2026-12-28", "2027-01-01", "2027-01-04", "2027-01-18",
                           "2027-02-15"], 3))
    body = ("import datetime\n    d = datetime.date.fromisoformat(start)\n    while n > 0:\n"
            "        d += datetime.timedelta(days=1)\n        if d.weekday() < 5 and d.isoformat() not in %r:\n"
            "            n -= 1\n    return d.isoformat()\n")
    rows = []
    for _ in range(CHECKS + 1):
        d = datetime.date(2026, 12, 1) + datetime.timedelta(days=r.randint(0, 60))
        rows.append((d.isoformat(), r.randint(0, 12)))
    return {"fn": "add_business_days", "text": (f"Write a Python function `add_business_days(start, n)` where `start` is an "
                                                f"ISO date string like '2026-12-01' and n >= 0. Return the ISO date "
                                                f"string that is n business days later: each counted day is a Monday to "
                                                f"Friday that is not one of these holidays: {', '.join(hol)}. The start "
                                                f"day itself is never counted, and n = 0 returns `start` unchanged."),
            "ref": "def add_business_days(start, n):\n    " + body % (hol,),
            "wrong": "def add_business_days(start, n):\n    " + body % ([],), "inputs": rows, "stratum": "algo-business"}


def _algo_wrap(r):
    w = r.randint(8, 24)
    body = ("lines, cur = [], ''\n    for word in text.split():\n"
            "        if cur and len(cur) + 1 + len(word) <= %d:\n            cur += ' ' + word\n"
            "        else:\n            if cur:\n                lines.append(cur)\n            cur = word\n"
            "    if cur:\n        lines.append(cur)\n    return lines\n")
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
             "kilo", "lima", "internationalization", "ok", "a", "zebra"]
    rows = [(" ".join(r.choice(words) for _ in range(r.randint(0, 9))),) for _ in range(CHECKS + 1)]
    return {"fn": "wrap_text", "text": (f"Write a Python function `wrap_text(text)` that splits `text` into words on "
                                        f"whitespace and packs them greedily into lines of at most {w} characters, words "
                                        f"separated by one space, never splitting a word (a word longer than {w} sits "
                                        f"alone on its line). Return the list of lines; no words gives an empty list."),
            "ref": "def wrap_text(text):\n    " + body % w, "wrong": "def wrap_text(text):\n    " + body % (w + 1),
            "inputs": rows, "stratum": "algo-wrap"}


def _algo_bits(r):
    k = r.randint(1, 5)
    body = "return sum(1 for x in range(lo, hi + 1) if bin(x).count('1') %s %d)\n"
    rows = []
    for _ in range(CHECKS + 1):
        lo = r.randint(0, 40)
        rows.append((lo, lo + r.randint(0, 60)))
    return {"fn": "count_bits", "text": (f"Write a Python function `count_bits(lo, hi)` returning how many integers x with "
                                         f"lo <= x <= hi (both inclusive, lo >= 0) have exactly {k} bit{'s' if k > 1 else ''} "
                                         f"set to 1 in binary. If hi < lo the answer is 0."),
            "ref": "def count_bits(lo, hi):\n    " + body % ("==", k), "wrong": "def count_bits(lo, hi):\n    " + body % (">=", k),
            "inputs": rows, "stratum": "algo-bits"}


def _algo_leaper(r):
    a, b = r.choice([(1, 2), (1, 3), (2, 3), (1, 4), (2, 5), (1, 1)])
    body = ("from collections import deque\n    h, w = len(grid), len(grid[0])\n"
            "    jumps = {(sa * x, sb * y) for x, y in ((%d, %d), (%d, %d)) for sa in (1, -1) for sb in (1, -1)}\n"
            "    dist, queue = {start: 0}, deque([start])\n    while queue:\n        cur = queue.popleft()\n"
            "        for dr, dc in jumps:\n            nxt = (cur[0] + dr, cur[1] + dc)\n"
            "            if 0 <= nxt[0] < h and 0 <= nxt[1] < w and grid[nxt[0]][nxt[1]] != '#' and nxt not in dist:\n"
            "                dist[nxt] = dist[cur] + 1\n                queue.append(nxt)\n    return dist.get(goal, -1)\n")
    rows = []
    for _ in range(CHECKS + 1):
        h, w = r.randint(4, 8), r.randint(4, 8)
        g = [["#" if r.random() < 0.15 else "." for _ in range(w)] for _ in range(h)]
        g[0][0] = g[-1][-1] = "."
        rows.append((["".join(row) for row in g], (0, 0), (h - 1, w - 1)))
    shape = f"{a} cells along one axis and {b} along the other" if a != b else f"{a} cells diagonally or {a} along an axis"
    ref = body % (a, b, b, a) if a != b else body % (a, b, a, a)
    wrong = body % (a, b + 1, b + 1, a)
    return {"fn": "min_jumps", "text": (f"Write a Python function `min_jumps(grid, start, goal)`. `grid` is a list of equal-length "
                                        f"strings of '.' (open) and '#' (blocked); `start` and `goal` are (row, col) tuples of "
                                        f"open cells. A piece moves like a chess knight but jumps {shape}, in any of the "
                                        f"orientations that gives (both signs on both axes, either axis first). It jumps "
                                        f"over anything but must land on an open cell inside the grid. Return the fewest "
                                        f"jumps from `start` to `goal`, or -1 if it cannot get there."),
            "ref": "def min_jumps(grid, start, goal):\n    " + ref, "wrong": "def min_jumps(grid, start, goal):\n    " + wrong,
            "inputs": rows, "stratum": "hard-leaper"}


def _algo_cuts(r):
    fee = r.randint(0, 4)
    body = ("pts = [0] + sorted(cuts) + [length]\n    n = len(pts)\n    dp = [[0] * n for _ in range(n)]\n"
            "    for span in range(2, n):\n        for i in range(n - span):\n            j = i + span\n"
            "            dp[i][j] = min(dp[i][k] + dp[k][j] for k in range(i + 1, j)) + pts[j] - pts[i] + %d\n"
            "    return dp[0][n - 1]\n")
    rows = []
    for _ in range(CHECKS + 1):
        n = r.randint(1, 11)
        length = r.randint(n + 1, 60)
        rows.append((length, r.sample(range(1, length), n)))
    return {"fn": "cutting_cost", "text": (f"Write a Python function `cutting_cost(length, cuts)`. A stick of the given length "
                                           f"must be cut at every position in `cuts` (distinct integers strictly between 0 and "
                                           f"`length`, in any order); the cuts may be made in any order. Making one cut costs "
                                           f"the current length of the piece being cut plus a fixed fee of {fee}. Return the "
                                           f"minimum total cost of making all the cuts (0 if there are none)."),
            "ref": "def cutting_cost(length, cuts):\n    " + body % fee,
            "wrong": "def cutting_cost(length, cuts):\n    " + body % (fee + 1), "inputs": rows, "stratum": "hard-cuts"}


def _algo_runs(r):
    q, k = r.randint(2, 4), r.randint(2, 4)
    mod = r.choice([1000, 10007, 1_000_000_007])
    body = ("if n == 0:\n        return 1\n    run = [0] * %d\n    run[1] = %d %% %d\n    for _ in range(n - 1):\n"
            "        total = sum(run)\n        nxt = [0] * %d\n        nxt[1] = total * %d %% %d\n"
            "        for j in range(1, %d):\n            nxt[j + 1] = run[j]\n        run = nxt\n    return sum(run) %% %d\n")
    ref = body % (k, q, mod, k, q - 1, mod, k - 1, mod)
    wrong = body % (k + 1, q, mod, k + 1, q - 1, mod, k, mod)
    rows = [(n,) for n in (0, 1, 2, 5, 9, r.randint(10, 60), r.randint(1000, 30000), 100000)]
    return {"fn": "count_strings", "text": (f"Write a Python function `count_strings(n)` returning, modulo {mod}, how many strings of "
                                            f"length n over an alphabet of {q} distinct letters contain no letter {k} times in a "
                                            f"row (a run of {k} equal adjacent letters is forbidden; shorter runs are fine). "
                                            f"n = 0 counts the empty string once. n can be as large as 100000."),
            "ref": "def count_strings(n):\n    " + ref, "wrong": "def count_strings(n):\n    " + wrong, "inputs": rows,
            "stratum": "hard-runs"}


def _algo_recurrence(r):
    c = [r.randint(1, 5) for _ in range(3)]
    a0 = [r.randint(0, 4) for _ in range(3)]
    mod = r.choice([1000, 998244353, 1_000_000_007])
    body = ("def mul(x, y):\n        return [[sum(x[i][t] * y[t][j] for t in range(3)) %% %d for j in range(3)] "
            "for i in range(3)]\n    if n < 3:\n        return %r[n] %% %d\n"
            "    m, out = [[%d, %d, %d], [1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]\n"
            "    e = n - 2\n    while e:\n        if e & 1:\n            out = mul(out, m)\n        m = mul(m, m)\n"
            "        e >>= 1\n    return (out[0][0] * %d + out[0][1] * %d + out[0][2] * %d) %% %d\n")
    ref = body % (mod, a0, mod, c[0], c[1], c[2], a0[2], a0[1], a0[0], mod)
    wrong = body % (mod, a0, mod, c[0], c[2], c[1], a0[2], a0[1], a0[0], mod)
    rows = [(n,) for n in (0, 2, 3, 7, 20, r.randint(10 ** 6, 10 ** 9), 10 ** 18 - r.randint(1, 999), 2 ** 62 + r.randint(0, 99))]
    return {"fn": "term", "text": (f"Write a Python function `term(n)` returning the n-th term, modulo {mod}, of the sequence "
                                   f"a(0) = {a0[0]}, a(1) = {a0[1]}, a(2) = {a0[2]} and, for n >= 3, a(n) = {c[0]} * a(n-1) + "
                                   f"{c[1]} * a(n-2) + {c[2]} * a(n-3). n can be as large as 10**18."),
            "ref": "def term(n):\n    " + ref, "wrong": "def term(n):\n    " + wrong, "inputs": rows, "stratum": "hard-recurrence"}


def _algo_popcount(r):
    k = r.randint(2, 8)
    body = ("from math import comb\n    if hi < lo:\n        return 0\n    def upto(m):\n        if m < 0:\n            return 0\n"
            "        bits, ones, res = bin(m)[2:], 0, 0\n        for i, b in enumerate(bits):\n"
            "            if b == '1':\n                rem, need = len(bits) - i - 1, %d - ones\n"
            "                if 0 <= need <= rem:\n                    res += comb(rem, need)\n                ones += 1\n"
            "        return res + (ones == %d)\n    return upto(hi) - upto(lo - 1)\n")
    rows = []
    for _ in range(CHECKS + 1):
        lo = r.randint(0, 10 ** r.choice([3, 8, 12, 15]))
        rows.append((lo, lo + r.randint(0, 10 ** r.choice([3, 9, 13, 15]))))
    return {"fn": "count_bits", "text": (f"Write a Python function `count_bits(lo, hi)` returning how many integers x with lo <= x <= hi "
                                         f"(both inclusive, 0 <= lo) have exactly {k} bits set to 1 in binary; hi can be as large as "
                                         f"10**15, so counting one by one is too slow. If hi < lo the answer is 0."),
            "ref": "def count_bits(lo, hi):\n    " + body % (k, k), "wrong": "def count_bits(lo, hi):\n    " + body % (k + 1, k + 1),
            "inputs": rows, "stratum": "hard-popcount"}


def _algo_gcdpairs(r):
    d = r.randint(1, 6)
    body = ("m = n // " + str(d) + "\n    phi = list(range(m + 1))\n    for p in range(2, m + 1):\n        if phi[p] == p:\n"
            "            for q in range(p, m + 1, p):\n                phi[q] -= phi[q] // p\n"
            "    return sum(phi[2:]) %s\n")
    rows = [(n,) for n in (0, 1, 7, 30, r.randint(100, 900), r.randint(5000, 60000), 400000, 1000000)]
    return {"fn": "count_pairs", "text": (f"Write a Python function `count_pairs(n)` returning how many pairs (i, j) with 1 <= i < j <= n "
                                          f"have gcd(i, j) equal to exactly {d}. n can be as large as 1000000, so checking every pair "
                                          f"is too slow."),
            "ref": "def count_pairs(n):\n    " + body % "", "wrong": "def count_pairs(n):\n    " + body % f"+ n // {d}",
            "inputs": rows, "stratum": "hard-gcdpairs"}


def _algo_tour(r):
    back = r.random() < 0.5
    body = ("n = len(dist)\n    if n <= 1:\n        return 0\n    INF = float('inf')\n"
            "    best = [[INF] * n for _ in range(1 << n)]\n    best[1][0] = 0\n"
            "    for mask in range(1 << n):\n        for last in range(n):\n"
            "            cur = best[mask][last]\n            if cur == INF:\n                continue\n"
            "            for nxt in range(n):\n                if not mask >> nxt & 1:\n"
            "                    key = mask | 1 << nxt\n"
            "                    best[key][nxt] = min(best[key][nxt], cur + dist[last][nxt])\n"
            "    full = (1 << n) - 1\n    return min(best[full][i] %s for i in range(n))\n")
    rows = []
    for _ in range(CHECKS + 1):
        n = r.randint(2, 7)
        rows.append(([[0 if i == j else r.randint(1, 30) for j in range(n)] for i in range(n)],))
    plus = "+ dist[i][0]" if back else ""
    other = "" if back else "+ dist[i][0]"
    word = ("and returns to location 0" if back else "and may stop at any location when the last one is reached")
    return {"fn": "route_cost", "text": (f"Write a Python function `route_cost(dist)` where `dist` is an n x n matrix of non-negative "
                                         f"integers, dist[i][j] being the cost of travelling directly from location i to location j "
                                         f"(it need not be symmetric or obey the triangle inequality). A route starts at location 0, "
                                         f"visits every other location exactly once {word}. Return the minimum total cost; 0 if n <= 1."),
            "ref": "def route_cost(dist):\n    " + body % plus, "wrong": "def route_cost(dist):\n    " + body % other,
            "inputs": rows, "stratum": "hard-tour"}


def _algo_waiting(r):
    body = ("import heapq\n    best, heap = {0: 0}, [(0, 0)]\n    while heap:\n        t, u = heapq.heappop(heap)\n"
            "        if t > best.get(u, float('inf')):\n            continue\n        for a, b, w, p, o in edges:\n"
            "            if a != u:\n                continue\n            start = t + (o - t) %% p\n"
            "            if start %s t:\n                start = t\n"
            "            arrive = start + w\n            if arrive < best.get(b, float('inf')):\n"
            "                best[b] = arrive\n                heapq.heappush(heap, (arrive, b))\n"
            "    return best.get(n - 1, -1)\n")
    rows = []
    for _ in range(CHECKS + 1):
        n = r.randint(2, 6)
        edges = []
        for _ in range(r.randint(n, 2 * n + 2)):
            a, b = r.randrange(n), r.randrange(n)
            if a != b:
                p = r.randint(1, 6)
                edges.append((a, b, r.randint(1, 9), p, r.randrange(p)))
        rows.append((n, edges))
    return {"fn": "earliest_arrival", "text": ("Write a Python function `earliest_arrival(n, edges)`: nodes 0..n-1 and directed edges "
                                               "(a, b, w, p, o). You can start travelling along an edge only at a time t with t % p == o "
                                               "(t is a non-negative integer); the trip takes w time units. You may wait at a node for "
                                               "free. You are at node 0 at time 0. Return the earliest time you can be at node n-1, or "
                                               "-1 if you cannot get there; if n is 1 the answer is 0."),
            "ref": "def earliest_arrival(n, edges):\n    " + body % "<", "wrong": "def earliest_arrival(n, edges):\n    " + body.replace(
                "start = t + (o - t) %% p", "start = t + (o - t) %% p + 1") % "<",
            "inputs": rows, "stratum": "hard-waiting"}


def _algo_rank(r):
    descending, zero = r.random() < 0.5, r.random() < 0.5
    body = ("from collections import Counter\n    from math import factorial\n    counts, rank = Counter(s), %d\n"
            "    for i, ch in enumerate(s):\n        for other in sorted(counts, reverse=%r):\n"
            "            if other == ch:\n                break\n            if counts[other]:\n"
            "                counts[other] -= 1\n                perms = factorial(len(s) - i - 1)\n"
            "                for c in counts.values():\n                    perms //= factorial(c)\n"
            "                rank += perms\n                counts[other] += 1\n        counts[ch] -= 1\n    return rank\n")
    words = ["banana", "mississippi", "aabb", "abc", "zzyx", "hello", "a", "", "xyzzyx", "success", "tattoo", "cabbage", "aaa"]
    rows = [(w,) for w in r.sample(words, CHECKS + 1)]
    order = "descending" if descending else "ascending"
    base = 0 if zero else 1
    return {"fn": "perm_rank", "text": (f"Write a Python function `perm_rank(s)` returning the position of the string `s` in the sorted list "
                                        f"of all DISTINCT permutations of its characters (repeated characters give repeated permutations "
                                        f"only once), sorted by code point in {order} order. The first permutation has position {base}. "
                                        f"The empty string has position {base}."),
            "ref": "def perm_rank(s):\n    " + body % (base, descending), "wrong": "def perm_rank(s):\n    " + body % (base, not descending),
            "inputs": rows, "stratum": "hard-rank"}


ALGOS = [_algo_ways, _algo_coins, _algo_chain, _algo_subsets, _algo_paths, _algo_edit, _algo_josephus, _algo_robin,
         _algo_cache, _algo_merge, _algo_union, _algo_stack, _algo_brackets, _algo_rotate, _algo_business,
         _algo_wrap, _algo_bits, _algo_leaper, _algo_cuts, _algo_runs, _algo_recurrence, _algo_popcount, _algo_gcdpairs,
         _algo_tour, _algo_waiting, _algo_rank]
#: One round of 20 draws: the share of each family.
FAMILIES = ["ints"] * 4 + ["strs"] * 6 + ["records"] * 2 + ["algo"] * 8


def _build(r: random.Random, family: str, used: dict) -> dict:
    if family == "algo":
        template = r.choice([a for a in ALGOS if used.get(a.__name__, 0) < TEMPLATE_CAP])
        return {**template(r), "template": template.__name__}
    return _records(r) if family == "records" else _pipeline(r, family)


def _call(fn: str, args: tuple) -> str:
    return f"{fn}({', '.join(repr(a) for a in args)})"


def _run(source: str, fn: str, inputs: list[tuple]) -> list:
    import copy
    ns: dict = {}
    exec(source, ns)  # noqa: S102 - the generator's own reference, never model output
    return [ns[fn](*copy.deepcopy(a)) for a in inputs]


def _finish(p: dict) -> dict | None:
    """The case's checks and example, or None when the draw is degenerate, unstable or too weak a trap."""
    try:
        want = _run(p["ref"], p["fn"], p["inputs"])
        shared = max(want[:-1].count(w) for w in want[:-1])
        if len({repr(w) for w in want[:-1]}) < 3 or shared > CHECKS // 2:
            return None
        try:
            got = _run(p["wrong"], p["fn"], p["inputs"][:-1])
        except Exception:
            got = None
        if got is not None and got == want[:-1]:
            return None
        checks = [f"{_call(p['fn'], a)} == {w!r}" for a, w in zip(p["inputs"][:-1], want)]
        checks = [c for c in checks if len(c) <= 240]
        if len(checks) < CHECKS - 1:
            return None
        example = f"{_call(p['fn'], p['inputs'][-1])} returns {want[-1]!r}"
    except Exception:
        return None
    return {"checks": checks, "example": example}


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a draw whose prompt repeats an earlier one is drawn again."""
    out, seen, used = [], set(), {}
    for i in range(count):
        r = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        for _ in range(ATTEMPTS):
            p = _build(r, FAMILIES[i % len(FAMILIES)], used)
            done = _finish(p)
            if done and p["text"] not in seen:
                break
        else:
            raise ValueError(f"code_synth item {i}: no usable draw in {ATTEMPTS} attempts")
        seen.add(p["text"])
        used[p.get("template", "")] = used.get(p.get("template", ""), 0) + 1
        out.append({"item": i, "seed": seed, "fn": p["fn"], "text": p["text"], "ref": p["ref"],
                    "wrong": p["wrong"], "stratum": p["stratum"], **done})
    return out


def convert(row: dict) -> Imported:
    cid = f"code-synth-{row['item']:04d}"
    prompt = (f"{row['text']}\n\nExample: `{row['example']}`.\n\nReturn only the code.")
    att = provenance(sys.modules[__name__], row["item"], TRANSFORM, DATE)
    att.update(version=VERSION, seed=row["seed"], stratum=row["stratum"])
    case = {"id": cid, "modality": LANE, "prompt": prompt, "assert": {"checks": row["checks"]}, "attribution": att}
    wrong = f"# Imported by evals/importers from {SOURCE}: a deliberately wrong answer, never graded.\n{row['wrong']}"
    return Imported(case, row["ref"], files=((f"wrong/{cid}.py", wrong.encode("utf-8")),))


_CONSTANT = "def {fn}(*a, **k):\n    return {value}\n"


def _beside(case, folder: str) -> str:
    return (case.source.parent / folder / f"{case.id}.py").read_text(encoding="utf-8")


def _constant(value: str):
    return lambda case: _CONSTANT.format(fn=case.assertions["checks"][0].split("(", 1)[0], value=value)


#: The negative control: the reference must pass; the wrong variant and a constant answer must not.
RESPONDERS = {
    "reference": lambda case: _beside(case, "reference"),
    "wrong": lambda case: _beside(case, "wrong"),
    "none": _constant("None"),
    "zero": _constant("0"),
}


def passes(case, answer: str) -> bool:
    from harness.checks import code
    return code.check(answer, case.assertions["checks"]).ok
