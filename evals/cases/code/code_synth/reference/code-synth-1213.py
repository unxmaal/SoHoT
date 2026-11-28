# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = xs[::-1]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * -2 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * 3 for x in xs]
    xs = xs[:6]
    xs = sorted(xs, key=abs)
    xs = [x + 6 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::3]
    xs = xs[-2:]
    xs = [x for x in xs if x % 2 == 0]
    xs = list(dict.fromkeys(xs))
    return sum(xs)
