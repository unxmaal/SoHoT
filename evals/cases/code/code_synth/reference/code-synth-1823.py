# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = [min(2, max(-5, x)) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::3]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = xs[:3]
    xs = [min(2, max(-3, x)) for x in xs]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return xs.index(max(xs)) if xs else -1
