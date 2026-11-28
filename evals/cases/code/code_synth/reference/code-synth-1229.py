# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    xs = [x * 5 for x in xs]
    xs = xs[-3:]
    xs = [x for x in xs if x % 7 != 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = xs[:4]
    xs = [x for x in xs if x > 5]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -1 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return xs.index(max(xs)) if xs else -1
