# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs)
    xs = [x * -1 for x in xs]
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x * 3 for x in xs]
    xs = [min(3, max(-4, x)) for x in xs]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = xs[-5:]
    xs = [x % 9 for x in xs]
    return sorted(xs)[:2]
