# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = [x % 7 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [min(10, max(1, x)) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return sum(xs)
