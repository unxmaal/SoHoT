# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = xs[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    if xs:
        k = 5 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[::2]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-3:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 6 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    return len(set(xs))
