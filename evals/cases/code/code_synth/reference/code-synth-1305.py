# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x + -9 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = xs[-4:]
    xs = sorted(xs, key=abs)
    xs = [min(3, max(-1, x)) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + 4 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[:5]
    xs = [x % 3 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs.index(max(xs)) if xs else -1
