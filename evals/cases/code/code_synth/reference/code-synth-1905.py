# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [abs(x) for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 4) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:4]
    xs = [x * -2 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[:6]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    return xs
