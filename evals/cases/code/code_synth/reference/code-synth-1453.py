# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[::-1]
    xs = [x * 2 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [x + -9 for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x * x for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x for x in xs if x > -1]
    xs = xs[::-1]
    return max(xs) if xs else -1
