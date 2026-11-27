# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = list(dict.fromkeys(xs))
    xs = xs[:5]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
