# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(xs):
    xs = xs[3:]
    xs = [x for x in xs if x % 2 == 0]
    xs = [x * 2 for x in xs]
    xs = [abs(x) for x in xs]
    xs = xs[-4:]
    xs = [x * 2 for x in xs]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 7 != 0]
    xs = xs[:5]
    xs = xs[::-1]
    xs = sorted(xs)
    xs = [x for x in xs if x > 6]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    return max(xs) if xs else -1
