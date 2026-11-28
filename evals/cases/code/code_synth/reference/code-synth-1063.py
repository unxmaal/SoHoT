# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [x // 3 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = xs[:6]
    xs = [int(x / 4) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 2 == 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x // 2 for x in xs]
    xs = xs[-5:]
    return sorted(xs)[:2]
