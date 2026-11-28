# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [x * 3 for x in xs]
    xs = xs[:4]
    xs = [x for x in xs if x >= 0]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [x + -9 for x in xs]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:3]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x // 2 for x in xs]
    xs = list(dict.fromkeys(xs))
    return max(xs) if xs else -1
