# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for x in xs if x >= 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 4 for x in xs]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [x for x in xs if x > 6]
    xs = [x + -1 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    return xs.index(max(xs)) if xs else -1
