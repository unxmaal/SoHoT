# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 7 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = sorted(xs, key=abs)
    xs = [x // 2 for x in xs]
    return sum(xs)
