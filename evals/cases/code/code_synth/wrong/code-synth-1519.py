# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x for x in xs if x % 7 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 2) for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-3:]
    xs = [int(x / 4) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    return all(a < b for a, b in zip(xs, xs[1:]))
