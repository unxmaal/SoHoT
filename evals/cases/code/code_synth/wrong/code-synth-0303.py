# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [abs(x) for x in xs]
    xs = xs[::3]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -2]
    xs = sorted(xs, key=abs)
    xs = [x // 2 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::3]
    return max(xs) if xs else -1
