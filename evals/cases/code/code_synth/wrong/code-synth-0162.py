# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = xs[::-1]
    xs = [x // 4 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    return xs.index(max(xs)) if xs else -1
