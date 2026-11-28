# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = xs[-4:]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [min(0, max(-5, x)) for x in xs]
    return xs
