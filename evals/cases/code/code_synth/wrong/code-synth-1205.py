# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x % 3 != 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 4 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [min(5, max(-2, x)) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x + 6 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = xs[:5]
    xs = [x % 8 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[-5:]
    return xs
