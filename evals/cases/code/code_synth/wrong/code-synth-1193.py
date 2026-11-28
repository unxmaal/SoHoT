# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x * 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = xs[-3:]
    xs = sorted(xs, reverse=True)
    xs = xs[::3]
    xs = [x for x in xs if x % 5 != 0]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + 4 for x in xs]
    xs = [x * 2 for x in xs]
    xs = xs[::-1]
    return xs
