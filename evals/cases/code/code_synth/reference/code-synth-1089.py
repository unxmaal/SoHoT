# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = [int(x / 3) for x in xs]
    xs = xs[::2]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(xs))
    xs = sorted(xs, reverse=True)
    xs = sorted(xs, key=abs)
    xs = xs[:5]
    xs = [x * 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x + 9 for x in xs]
    xs = xs[-3:]
    xs = [x // 2 for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x % 9 for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = xs[:4]
    xs = [x for x in xs if x > -1]
    xs = [abs(x) for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
