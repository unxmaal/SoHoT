# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = sorted(xs)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::2]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::2]
    xs = xs[-2:]
    return all(a < b for a, b in zip(xs, xs[1:]))
