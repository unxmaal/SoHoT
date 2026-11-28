# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x + 2 for x in xs]
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [int(x / 3) for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x + 9 for x in xs]
    xs = [min(6, max(-3, x)) for x in xs]
    xs = [int(x / 3) for x in xs]
    return sorted(xs)[:2]
