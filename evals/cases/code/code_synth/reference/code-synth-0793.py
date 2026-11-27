# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def longest_chain(xs):
    best = {}
    for x in xs:
        best[x] = max(best.get(x, 0), best.get(x - (-5), 0) + 1)
    return max(best.values()) if best else 0
