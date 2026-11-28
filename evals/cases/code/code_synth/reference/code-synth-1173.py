# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x % 7 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 6 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = xs[-5:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return sum(xs)
