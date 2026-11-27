# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [x % 5 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[:6]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::2]
    xs = [x for x in xs if x > 2]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return xs
