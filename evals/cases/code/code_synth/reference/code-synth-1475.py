# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = [abs(x) for x in xs]
    xs = xs[:2]
    xs = sorted(xs, key=abs)
    xs = [int(x / 3) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [int(x / 3) for x in xs]
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = xs[-3:]
    xs = sorted(xs)
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs)
    xs = sorted(xs, key=abs)
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
