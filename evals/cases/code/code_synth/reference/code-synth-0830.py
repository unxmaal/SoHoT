# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(rows):
    return sorted(((n, 1 + sum(1 for x in rows if x[2] > s)) for n, d, s in rows), key=lambda p: (p[1], p[0]))
