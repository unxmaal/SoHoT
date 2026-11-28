# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[1:]
    xs = xs[::-1]
    xs = [x for x in xs if x % 5 != 0]
    xs = [x + -9 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[3:]
    xs = [abs(x) for x in xs]
    xs = xs[::2]
    xs = [x % 5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [x * 5 for x in xs]
    return max(xs) if xs else -1
