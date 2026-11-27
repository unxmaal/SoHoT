# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[:5]
    xs = xs[::-1]
    xs = [x for x in xs if x % 3 != 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, reverse=True)
    xs = [x % 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return len(set(xs))
