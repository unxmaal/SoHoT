# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-5:]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x + -1 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * 5 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = xs[1:]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    return xs
