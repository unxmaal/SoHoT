# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = xs[-5:]
    xs = sorted(xs, key=abs)
    xs = [x * 2 for x in xs]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [x * x for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, reverse=True)
    xs = [int(x / 2) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return xs
