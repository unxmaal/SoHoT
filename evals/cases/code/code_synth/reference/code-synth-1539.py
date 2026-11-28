# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * -2 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[-5:]
    xs = xs[:6]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x // 3 for x in xs]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    return max(xs) if xs else -1
