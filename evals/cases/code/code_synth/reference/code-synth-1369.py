# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[3:]
    xs = list(dict.fromkeys(xs))
    xs = [x * -1 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = sorted(xs, key=abs)
    xs = [x * x for x in xs]
    xs = [x + -1 for x in xs]
    xs = xs[1:]
    xs = xs[:3]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [abs(x) for x in xs]
    xs = [x * 3 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = xs[-4:]
    return xs
