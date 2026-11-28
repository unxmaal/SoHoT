# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = sorted(xs)
    xs = xs[::3]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = [x * x for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x + 6 for x in xs]
    xs = [x * -1 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    return xs
