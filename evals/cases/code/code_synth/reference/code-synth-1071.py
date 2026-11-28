# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [x for x in xs if x % 5 != 0]
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = xs[-3:]
    xs = [x for x in xs if x > -3]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 4 != 0]
    xs = [x * x for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 2 for x in xs]
    xs = xs[:6]
    xs = [x * x for x in xs]
    xs = [abs(x) for x in xs]
    xs = sorted(xs)
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
