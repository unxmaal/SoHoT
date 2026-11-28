# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x * 3 for x in xs]
    xs = xs[:6]
    xs = [min(7, max(1, x)) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x * x for x in xs]
    xs = [x + -3 for x in xs]
    xs = [x // 3 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-2:]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    return max(xs) if xs else -1
