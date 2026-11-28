# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = xs[1:]
    xs = [x * x for x in xs]
    xs = [x // 4 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::2]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [int(x / 3) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[::2]
    xs = list(dict.fromkeys(xs))
    return xs
