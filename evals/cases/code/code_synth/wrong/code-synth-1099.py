# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(xs):
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::2]
    xs = [x + -5 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 5 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = [x // 3 for x in xs]
    return all(a < b for a, b in zip(xs, xs[1:]))
