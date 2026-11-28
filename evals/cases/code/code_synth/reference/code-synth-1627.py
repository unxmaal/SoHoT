# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x for x in xs if x > -1]
    xs = list(dict.fromkeys(xs))
    xs = [x + 4 for x in xs]
    xs = xs[:5]
    xs = [x for x in xs if x > 8]
    xs = [x % 6 for x in xs]
    xs = [x for x in xs if x % 2 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = sorted(xs, key=abs)
    xs = [abs(x) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 7 != 0]
    xs = [abs(x) for x in xs]
    return xs
