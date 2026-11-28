# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x for x in xs if x > -3]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + -3 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = [x * x for x in xs]
    xs = [x // 4 for x in xs]
    xs = [x % 5 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = [x + 6 for x in xs]
    xs = xs[:3]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = xs[::2]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
