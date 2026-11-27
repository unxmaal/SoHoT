# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = sorted(xs)
    xs = [int(x / 3) for x in xs]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * x for x in xs]
    xs = xs[:5]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 5 != 0]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 2) for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
