# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [x + 6 for x in xs]
    xs = [int(x / 4) for x in xs]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x % 9 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [x * x for x in xs]
    xs = [x for x in xs if x > 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs, key=abs)
    xs = xs[:6]
    xs = [x for x in xs if x % 4 != 0]
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    if xs:
        k = 3 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = [x % 4 for x in xs]
    xs = [x for x in xs if x % 7 != 0]
    xs = sorted(xs)
    return sum(xs)
