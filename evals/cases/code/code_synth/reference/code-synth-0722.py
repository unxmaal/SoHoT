# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(xs):
    xs = [x * -1 for x in xs]
    xs = xs[:6]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x % 8 for x in xs]
    xs = [x for x in xs if x >= 0]
    xs = [x for x in xs if x % 2 == 0]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
