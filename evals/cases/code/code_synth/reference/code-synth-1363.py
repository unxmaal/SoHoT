# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > -2]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs)
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x % 6 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x + 4 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return xs.index(max(xs)) if xs else -1
