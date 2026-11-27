# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 4 != 0]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [x % 8 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return sorted(xs)[:2]
