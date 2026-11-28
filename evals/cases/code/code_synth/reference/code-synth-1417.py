# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = sorted(xs, key=abs)
    xs = [x % 4 for x in xs]
    xs = [x for x in xs if x > 2]
    xs = [x % 5 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(xs))
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    return sum(xs)
