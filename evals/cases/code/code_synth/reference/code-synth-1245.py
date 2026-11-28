# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [int(x / 3) for x in xs]
    xs = [min(2, max(-4, x)) for x in xs]
    xs = xs[:3]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = [x + 4 for x in xs]
    xs = sorted(xs, key=abs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 3 != 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[-2:]
    xs = xs[:4]
    xs = [x for x in xs if x >= 0]
    xs = list(dict.fromkeys(xs))
    return max(xs) if xs else -1
