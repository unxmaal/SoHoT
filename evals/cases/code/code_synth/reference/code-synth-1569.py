# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x * -2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + 2 for x in xs]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = xs[-2:]
    xs = sorted(xs, key=abs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
