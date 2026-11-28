# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x for x in xs if x % 2 != 0]
    xs = [min(1, max(-4, x)) for x in xs]
    xs = [x * 5 for x in xs]
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:5]
    xs = [x for x in xs if x % 4 != 0]
    xs = [int(x / 3) for x in xs]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x % 4 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    return sorted(xs)[:2]
