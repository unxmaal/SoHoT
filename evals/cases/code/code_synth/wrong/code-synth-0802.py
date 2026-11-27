# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [min(4, max(0, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::2]
    xs = [x + 9 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 != 0]
    xs = [min(-1, max(-5, x)) for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
