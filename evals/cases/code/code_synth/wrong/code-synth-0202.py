# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [abs(x) for x in xs]
    xs = xs[1:]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 7 != 0]
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    return all(a < b for a, b in zip(xs, xs[1:]))
