# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [x * -2 for x in xs]
    xs = xs[:6]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = [x % 3 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    return len(set(xs))
