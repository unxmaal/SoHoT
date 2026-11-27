# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = xs[3:]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x > -2]
    xs = xs[::-1]
    xs = sorted(xs, key=abs)
    xs = [x for x in xs if x > 0]
    xs = xs[-2:]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
