# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x % 3 != 0]
    xs = sorted(xs)
    xs = xs[-2:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
