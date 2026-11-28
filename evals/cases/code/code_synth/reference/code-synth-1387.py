# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x > 5]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 3]
    xs = xs[1:]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = xs[-4:]
    xs = xs[:5]
    xs = [int(x / 2) for x in xs]
    xs = [x + -3 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[-4:]
    return max(xs) if xs else -1
