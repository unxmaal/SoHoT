# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = xs[-3:]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -2]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return xs
