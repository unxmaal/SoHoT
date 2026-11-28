# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(4, max(1, x)) for x in xs]
    xs = [x * -2 for x in xs]
    xs = xs[::2]
    xs = [x + 6 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x % 6 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = xs[::-1]
    return max(xs) if xs else -1
