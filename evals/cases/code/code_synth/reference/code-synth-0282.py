# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = xs[:2]
    xs = [abs(x) for x in xs]
    xs = [x % 4 for x in xs]
    xs = xs[-4:]
    return len(set(xs))
