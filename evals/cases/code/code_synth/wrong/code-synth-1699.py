# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = [int(x / 3) for x in xs]
    xs = xs[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * -1 for x in xs]
    xs = xs[-4:]
    xs = sorted(xs, reverse=True)
    xs = [x + 4 for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 4 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = sorted(xs)
    return sorted(xs)[:2]
