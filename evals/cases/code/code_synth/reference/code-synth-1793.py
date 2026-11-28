# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x >= 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-2:]
    xs = [x % 7 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    xs = xs[:6]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x + 4 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 3) for x in xs]
    return sorted(xs)[:2]
