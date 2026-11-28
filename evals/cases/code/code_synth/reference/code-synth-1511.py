# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::3]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x * 2 for x in xs]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::3]
    xs = xs[-3:]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs)
    return sum(xs)
