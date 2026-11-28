# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = xs[1:]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 8 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [x + 9 for x in xs]
    xs = xs[:2]
    xs = xs[::2]
    xs = sorted(xs, reverse=True)
    xs = [abs(x) for x in xs]
    xs = [x % 4 for x in xs]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
