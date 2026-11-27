# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 5]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
