# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x + -9 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = sorted(xs)
    xs = [x * -2 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    xs = xs[:6]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    xs = xs[-3:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    return sorted(xs)[:2]
