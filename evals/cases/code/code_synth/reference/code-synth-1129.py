# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x + -5 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 2 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x + 6 for x in xs]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [int(x / 2) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = xs[-2:]
    return sum(xs)
