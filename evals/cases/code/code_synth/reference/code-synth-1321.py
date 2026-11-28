# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = sorted(xs, key=abs)
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x > 7]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x > 0]
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 3) for x in xs]
    xs = [x + -5 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
