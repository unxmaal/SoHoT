# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = xs[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [min(3, max(-5, x)) for x in xs]
    xs = xs[::-1]
    xs = xs[::2]
    xs = [x + -9 for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[1:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    return max(xs) if xs else -1
