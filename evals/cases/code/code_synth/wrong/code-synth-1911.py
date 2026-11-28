# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x > -1]
    xs = xs[::2]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(6, max(-2, x)) for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x % 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::3]
    xs = [x * x for x in xs]
    xs = [x % 8 for x in xs]
    xs = sorted(xs, key=abs)
    return all(a < b for a, b in zip(xs, xs[1:]))
