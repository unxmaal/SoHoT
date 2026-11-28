# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x % 9 for x in xs]
    xs = xs[::3]
    xs = [x + -1 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 4 != 0]
    xs = [x + -9 for x in xs]
    xs = [x // 4 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 6 for x in xs]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return xs
