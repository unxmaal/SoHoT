# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    if xs:
        k = 2 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for x in xs if x > -3]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-5:]
    xs = [int(x / 4) for x in xs]
    xs = sorted(xs)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
