# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x // 4 for x in xs]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = sorted(xs, key=abs)
    xs = xs[::3]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x // 4 for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = list(dict.fromkeys(xs))
    xs = xs[:6]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x // 2 for x in xs]
    xs = xs[-4:]
    return sorted(xs)[:2]
