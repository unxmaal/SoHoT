# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::-1]
    xs = [int(x / 4) for x in xs]
    xs = [x * 3 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [x + -5 for x in xs]
    return xs.index(max(xs)) if xs else -1
