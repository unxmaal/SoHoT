# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = xs[3:]
    xs = [x for x in xs if x >= 0]
    xs = xs[-5:]
    xs = sorted(xs)
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 5 != 0]
    return max(xs) if xs else -1
