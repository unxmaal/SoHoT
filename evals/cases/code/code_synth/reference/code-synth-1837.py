# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = sorted(xs)
    xs = xs[2:]
    xs = [min(5, max(0, x)) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x >= 0]
    xs = [x * x for x in xs]
    xs = [x * -1 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 6 for x in xs]
    xs = [x % 9 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, key=abs)
    return xs
