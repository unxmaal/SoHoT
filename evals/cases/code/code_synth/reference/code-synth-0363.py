# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x + 2 for x in xs]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 2 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
