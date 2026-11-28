# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[:5]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [x % 8 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * -2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    return sorted(xs)[:2]
