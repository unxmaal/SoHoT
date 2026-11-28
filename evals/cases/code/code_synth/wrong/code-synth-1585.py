# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = sorted(xs)
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, key=abs)
    xs = [min(6, max(0, x)) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x % 6 for x in xs]
    return max(xs) if xs else -1
