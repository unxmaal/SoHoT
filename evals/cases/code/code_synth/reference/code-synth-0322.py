# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = xs[-3:]
    xs = xs[::-1]
    xs = [x for x in xs if x >= 0]
    xs = [max(xs[max(0, i - 3):i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = xs[::3]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
