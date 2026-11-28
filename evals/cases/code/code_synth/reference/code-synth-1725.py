# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-4:]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 8 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[:5]
    xs = sorted(xs, key=abs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    return sorted(xs)[:2]
