# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x * -1 for x in xs]
    xs = xs[1:]
    xs = [x for x in xs if x > -2]
    xs = [x % 4 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = [x + -9 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x * 5 for x in xs]
    xs = xs[::-1]
    xs = xs[::-1]
    xs = [x + -1 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs
