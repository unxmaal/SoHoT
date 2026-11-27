# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [int(x / 3) for x in xs]
    xs = xs[:6]
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    return sum(xs)
