# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def count_subsets(nums, target):
    ways = {0: 1}
    for x in nums:
        for s, c in list(ways.items()):
            ways[s + x] = ways.get(s + x, 0) + c
    return ways.get(target, 0) % 7
