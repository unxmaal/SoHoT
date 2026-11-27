# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x % 9 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [min(5, max(-1, x)) for x in xs]
    return xs
