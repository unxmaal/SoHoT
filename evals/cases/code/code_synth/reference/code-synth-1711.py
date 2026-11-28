# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = xs[::-1]
    xs = [int(x / 4) for x in xs]
    xs = xs[::-1]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [abs(x) for x in xs]
    xs = [int(x / 3) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, key=abs)
    return sum(xs)
