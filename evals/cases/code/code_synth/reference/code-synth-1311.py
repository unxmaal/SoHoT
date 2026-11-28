# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = xs[::-1]
    xs = xs[-5:]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs)
    xs = [int(x / 4) for x in xs]
    xs = [x % 9 for x in xs]
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[1:]
    xs = [x % 8 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    return max(xs) if xs else -1
