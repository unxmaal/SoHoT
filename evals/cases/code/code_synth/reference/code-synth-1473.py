# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(xs):
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [max(xs[max(0, i - 1):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-4:]
    xs = xs[::3]
    xs = [x for x in xs if x % 3 != 0]
    xs = [x * -1 for x in xs]
    xs = [min(8, max(0, x)) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x // 2 for x in xs]
    xs = [abs(x) for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [abs(x) for x in xs]
    xs = [x + 9 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    if xs:
        k = 9 % len(xs)
        xs = xs[k:] + xs[:k]
    return sorted(xs)[:2]
