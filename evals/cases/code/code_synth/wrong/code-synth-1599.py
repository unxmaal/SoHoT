# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(xs):
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x for x in xs if x > 0]
    xs = [x % 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -9 for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = [abs(x) for x in xs]
    xs = xs[:2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return sum(xs)
