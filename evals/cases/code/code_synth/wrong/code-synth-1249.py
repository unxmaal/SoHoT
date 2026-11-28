# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = sorted(xs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = xs[::2]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > -1]
    xs = [x % 4 for x in xs]
    xs = xs[:2]
    xs = [min(1, max(-2, x)) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[-2:]
    return xs.index(max(xs)) if xs else -1
