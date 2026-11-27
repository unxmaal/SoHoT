# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [x * x for x in xs]
    xs = [x % 4 for x in xs]
    xs = [min(3, max(-5, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 2 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
