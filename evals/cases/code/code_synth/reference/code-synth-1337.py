# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[-5:]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 5 for x in xs]
    xs = xs[:5]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-5:]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x // 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [int(x / 2) for x in xs]
    return xs
