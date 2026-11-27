# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x % 9 for x in xs]
    xs = xs[-3:]
    xs = [min(8, max(1, x)) for x in xs]
    xs = xs[:6]
    xs = xs[-5:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 3) for x in xs]
    return sorted(xs)[:2]
