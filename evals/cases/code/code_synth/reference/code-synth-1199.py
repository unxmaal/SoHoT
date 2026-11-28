# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[3:]
    xs = [x for x in xs if x % 4 != 0]
    xs = sorted(xs, key=abs)
    xs = [x % 7 for x in xs]
    xs = xs[:3]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = xs[:5]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[:6]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [int(x / 3) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 2) for x in xs]
    return max(xs) if xs else -1
