# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x % 5 != 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[1:]
    xs = [min(6, max(1, x)) for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::2]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = [x * -2 for x in xs]
    xs = [x * x for x in xs]
    xs = [x * 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    return xs
