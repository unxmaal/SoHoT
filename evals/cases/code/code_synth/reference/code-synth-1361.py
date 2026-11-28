# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x % 6 for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x > 0]
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(1, max(-2, x)) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x > -3]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, reverse=True)
    xs = xs[-4:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * -2 for x in xs]
    return xs
