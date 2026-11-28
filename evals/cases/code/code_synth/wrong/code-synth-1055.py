# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x + 2 for x in xs]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [int(x / 3) for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x + 9 for x in xs]
    xs = [min(6, max(-3, x)) for x in xs]
    xs = [int(x / 3) for x in xs]
    return sorted(xs)[:2]
