# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = xs[-5:]
    xs = xs[::-1]
    xs = [x * 2 for x in xs]
    xs = [x for x in xs if x > -2]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, key=abs)
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return sum(xs)
