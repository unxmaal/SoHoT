# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x % 6 for x in xs]
    xs = [int(x / 2) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * x for x in xs]
    xs = [int(x / 4) for x in xs]
    return xs
