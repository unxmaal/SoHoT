# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = xs[:6]
    xs = sorted(xs)
    xs = [x for x in xs if x % 7 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -9 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return len(set(xs))
