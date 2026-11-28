# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x * 5 for x in xs]
    xs = [x % 8 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = [abs(x) for x in xs]
    xs = xs[:5]
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sum(xs)
