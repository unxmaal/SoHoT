# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = xs[::3]
    return xs
