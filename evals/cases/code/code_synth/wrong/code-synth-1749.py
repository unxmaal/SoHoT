# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[1:]
    xs = [x // 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    return xs
