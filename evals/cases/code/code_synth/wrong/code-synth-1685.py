# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x for x in xs if x >= 0]
    xs = [min(8, max(0, x)) for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[-5:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs)
    xs = [x * 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x % 9 for x in xs]
    xs = xs[:2]
    xs = xs[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return xs
