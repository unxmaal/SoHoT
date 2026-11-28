# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    xs = [x % 7 for x in xs]
    xs = [x + 2 for x in xs]
    xs = [x % 8 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = [x % 8 for x in xs]
    xs = xs[::2]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [min(6, max(-1, x)) for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 5 for x in xs]
    return sum(xs)
