# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x // 2 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x % 6 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[3:]
    xs = xs[-5:]
    xs = [x for x in xs if x % 4 != 0]
    xs = xs[::2]
    xs = [abs(x) for x in xs]
    xs = xs[::3]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = [min(4, max(-5, x)) for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
