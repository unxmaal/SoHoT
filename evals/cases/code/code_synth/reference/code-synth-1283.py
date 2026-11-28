# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = xs[::-1]
    xs = sorted(xs, reverse=True)
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x * -1 for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[-3:]
    xs = list(dict.fromkeys(xs))
    xs = xs[-5:]
    xs = [x // 2 for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    return sorted(xs)[:2]
