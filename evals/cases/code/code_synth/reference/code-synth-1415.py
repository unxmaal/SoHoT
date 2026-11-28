# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[-5:]
    xs = sorted(xs)
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = sorted(xs)
    xs = list(dict.fromkeys(xs))
    xs = [x + -5 for x in xs]
    return xs.index(max(xs)) if xs else -1
