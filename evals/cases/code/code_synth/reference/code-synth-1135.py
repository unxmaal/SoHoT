# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 3 for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x % 7 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -5 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [abs(x) for x in xs]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return xs.index(max(xs)) if xs else -1
