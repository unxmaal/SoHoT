# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(xs):
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x // 2 for x in xs]
    xs = [x for x in xs if x > 7]
    xs = xs[::2]
    xs = xs[-4:]
    xs = [x * x for x in xs]
    xs = sorted(xs, key=abs)
    if xs:
        k = 4 % len(xs)
        xs = xs[k:] + xs[:k]
    xs = sorted(xs, key=abs)
    xs = xs[::2]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = [x // 4 for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-2:]
    return sorted(xs)[:2]
