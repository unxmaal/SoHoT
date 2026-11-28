# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * 5 for x in xs]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 2 for x in xs]
    xs = xs[:4]
    xs = [x * 5 for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    xs = [min(4, max(-1, x)) for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x + 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return sum(xs)
