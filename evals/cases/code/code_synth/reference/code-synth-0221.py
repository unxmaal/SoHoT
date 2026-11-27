# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = xs[::-1]
    xs = xs[:3]
    xs = [x for x in xs if x > 7]
    return max(xs) if xs else -1
