# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = xs[2:]
    xs = [int(x / 3) for x in xs]
    xs = xs[-5:]
    xs = [x % 8 for x in xs]
    xs = [x // 2 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    xs = [min(6, max(1, x)) for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
