# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x * x for x in xs]
    xs = xs[-3:]
    xs = [int(x / 2) for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = xs[::2]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-3:]
    xs = [x for x in xs if x % 5 != 0]
    xs = xs[-2:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 2) for x in xs]
    xs = [x + -1 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = list(dict.fromkeys(xs))
    return sum(xs)
