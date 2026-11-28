# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x for x in xs if x > 6]
    xs = xs[:4]
    xs = [int(x / 4) for x in xs]
    xs = xs[::-1]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 5 for x in xs]
    xs = [x // 3 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[-4:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [min(7, max(0, x)) for x in xs]
    xs = xs[::3]
    return sorted(xs)[:2]
