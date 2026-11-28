# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = xs[:6]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x * -1 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x * 5 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::2]
    xs = [int(x / 4) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x % 6 for x in xs]
    xs = [x * 2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [min(1, max(-2, x)) for x in xs]
    return xs
