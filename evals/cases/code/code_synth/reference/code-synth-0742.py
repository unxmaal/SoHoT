# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[::3]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = xs[-3:]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::-1]
    return sum(xs)
