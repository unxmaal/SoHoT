# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x * 2 for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = sorted(xs, reverse=True)
    xs = xs[::3]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x % 6 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x % 9 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = sorted(xs, key=abs)
    return xs
