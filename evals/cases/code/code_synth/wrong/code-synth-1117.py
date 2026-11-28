# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x > -2]
    xs = xs[:6]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = xs[1:]
    xs = xs[:5]
    xs = [x for x in xs if x % 5 != 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 4 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-3:]
    xs = [x + 9 for x in xs]
    xs = [x // 4 for x in xs]
    xs = [x * x for x in xs]
    return sorted(xs)[:2]
