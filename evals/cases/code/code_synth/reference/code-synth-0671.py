# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(rows):
    return [n for n, d, s in sorted(rows, key=lambda x: (-x[2], x[0]))][:2]
