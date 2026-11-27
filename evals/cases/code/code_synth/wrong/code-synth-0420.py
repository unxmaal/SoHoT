# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 3) for x in xs]
    xs = xs[2:]
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    return len(set(xs))
