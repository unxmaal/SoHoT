# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for x in xs if x > -1]
    if xs:
        k = 1 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x * -1 for x in xs]
    xs = xs[::3]
    xs = xs[::-1]
    xs = xs[:4]
    xs = list(dict.fromkeys(xs))
    xs = xs[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    xs = [x for x in xs if x % 2 == 0]
    xs = xs[-4:]
    xs = xs[::-1]
    return max(xs) if xs else -1
