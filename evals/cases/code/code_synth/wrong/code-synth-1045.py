# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(6, max(-2, x)) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [min(5, max(-2, x)) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x // 4 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
