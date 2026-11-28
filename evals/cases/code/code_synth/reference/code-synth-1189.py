# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > -3]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = xs[:2]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sum(xs)
