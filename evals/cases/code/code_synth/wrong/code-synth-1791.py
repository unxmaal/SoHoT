# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x > 3]
    xs = [int(x / 3) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [x % 8 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x + -3 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
