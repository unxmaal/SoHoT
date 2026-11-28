# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[3:]
    xs = [x % 3 for x in xs]
    xs = [x + 4 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = [x * 2 for x in xs]
    xs = xs[-5:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[2:]
    return xs.index(max(xs)) if xs else -1
