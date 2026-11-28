# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * -1 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 2) for x in xs]
    xs = [x * 2 for x in xs]
    xs = xs[::3]
    xs = xs[:2]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x % 7 != 0]
    xs = list(dict.fromkeys(xs))
    return sum(xs)
