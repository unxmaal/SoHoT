# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [abs(x) for x in xs]
    xs = [x % 4 for x in xs]
    xs = xs[-4:]
    return len(set(xs))
