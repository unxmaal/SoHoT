# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * x for x in xs]
    xs = [x + -3 for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 4]
    xs = xs[2:]
    xs = xs[:4]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -5 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return xs
