# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(xs):
    xs = [x for x in xs if x % 3 != 0]
    xs = [int(x / 3) for x in xs]
    xs = [min(9, max(0, x)) for x in xs]
    xs = [b - a for a, b in zip(xs, xs[1:])]
    xs = list(dict.fromkeys(xs))
    xs = [x * -1 for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [abs(x) for x in xs]
    xs = xs[:6]
    xs = sorted(xs, reverse=True)
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[-2:]
    xs = [min(7, max(0, x)) for x in xs]
    xs = xs[:6]
    xs = xs[-3:]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x * 5 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return sorted(xs)[(len(xs) - 1) // 2] if xs else 0
