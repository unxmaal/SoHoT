# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = list(dict.fromkeys(xs))
    xs = xs[:5]
    return sum(xs)
