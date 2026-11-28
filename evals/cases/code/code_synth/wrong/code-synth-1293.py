# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 != 0]
    xs = xs[:3]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = xs[-5:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x % 9 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    return xs.index(max(xs)) if xs else -1
