# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * x for x in xs]
    xs = xs[-4:]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x * 5 for x in xs]
    xs = [x * x for x in xs]
    return xs
