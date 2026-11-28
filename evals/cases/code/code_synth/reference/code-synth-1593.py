# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = xs[:4]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for x in xs if x > 1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x > 3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:3]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    return max(xs) if xs else -1
