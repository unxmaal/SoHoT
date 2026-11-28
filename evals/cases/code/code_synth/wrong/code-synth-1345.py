# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[1:]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    xs = xs[1:]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return xs
