# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = xs[1:]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::2]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 3 != 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    if xs:
        k = 8 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs)
    return xs
