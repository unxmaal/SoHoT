# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = sorted(xs)
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x + -5 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * 2 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 2) for x in xs]
    xs = xs[:5]
    return sum(xs)
