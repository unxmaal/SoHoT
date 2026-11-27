# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x // 2 for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x * 5 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(2, max(-5, x)) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return sum(xs)
