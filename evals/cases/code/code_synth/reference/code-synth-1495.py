# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [x for x in xs if x > 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x + -3 for x in xs]
    xs = xs[-4:]
    xs = [x * x for x in xs]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [abs(x) for x in xs]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
