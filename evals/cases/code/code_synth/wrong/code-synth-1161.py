# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = [x * 5 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = xs[:6]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 2) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    return xs
