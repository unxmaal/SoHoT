# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = xs[:6]
    xs = sorted(xs)
    xs = [x for x in xs if x % 7 != 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -9 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sum(xs)
