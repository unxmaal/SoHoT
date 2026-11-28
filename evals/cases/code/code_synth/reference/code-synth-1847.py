# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = xs[::-1]
    xs = [x * x for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [int(x / 4) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[2:]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [int(x / 3) for x in xs]
    xs = [x % 8 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x >= 0]
    xs = [x * x for x in xs]
    xs = [x + -5 for x in xs]
    xs = sorted(xs, key=abs)
    xs = sorted(xs)
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
