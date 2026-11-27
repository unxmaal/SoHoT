# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(xs):
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[-3:]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
