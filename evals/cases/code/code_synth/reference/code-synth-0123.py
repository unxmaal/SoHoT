# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = [min(-2, max(-5, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[:4]
    xs = list(dict.fromkeys(xs))
    xs = [int(x / 3) for x in xs]
    xs = sorted(xs, reverse=True)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
