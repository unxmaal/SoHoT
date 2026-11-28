# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = list(dict.fromkeys(xs))
    xs = xs[:6]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[:4]
    xs = [x // 3 for x in xs]
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = xs[-3:]
    return max(xs) if xs else -1
