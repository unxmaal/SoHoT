# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = xs[:3]
    xs = [x * x for x in xs]
    xs = xs[::-1]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x + 4 for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + -1 for x in xs]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [x * x for x in xs]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x > -1]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
