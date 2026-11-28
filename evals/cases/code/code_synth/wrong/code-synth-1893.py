# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[-3:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [x + 9 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::3]
    xs = [int(x / 2) for x in xs]
    xs = xs[-3:]
    xs = xs[::2]
    xs = xs[:6]
    xs = [int(x / 3) for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::2]
    xs = [x for x in xs if x >= 0]
    return xs
