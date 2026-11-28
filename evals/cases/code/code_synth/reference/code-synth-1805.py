# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = xs[-4:]
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > 4]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = [x % 5 for x in xs]
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 7 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-2:]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [min(5, max(-4, x)) for x in xs]
    return sorted(xs)[:2]
