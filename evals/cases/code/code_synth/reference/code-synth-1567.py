# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x + 4 for x in xs]
    xs = xs[-5:]
    xs = [x * x for x in xs]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [x + -9 for x in xs]
    xs = [x * -1 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 4 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    return xs
