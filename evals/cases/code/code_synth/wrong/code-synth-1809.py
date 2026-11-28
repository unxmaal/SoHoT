# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-5:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 4 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-2:]
    xs = [x for x in xs if x >= 0]
    xs = [x % 9 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return xs.index(max(xs)) if xs else -1
