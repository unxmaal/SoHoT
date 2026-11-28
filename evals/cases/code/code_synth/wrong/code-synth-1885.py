# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = xs[-2:]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 2]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 4) for x in xs]
    return xs.index(max(xs)) if xs else -1
