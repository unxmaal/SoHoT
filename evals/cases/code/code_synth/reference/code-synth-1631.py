# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * -2 for x in xs]
    xs = [x % 4 for x in xs]
    xs = [x * 3 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x >= 0]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [x % 9 for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = [min(5, max(0, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-3:]
    xs = list(dict.fromkeys(xs))
    xs = [x % 7 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
