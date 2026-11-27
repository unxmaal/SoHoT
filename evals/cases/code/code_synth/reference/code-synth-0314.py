# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def first_bracket_error(s):
    stack = []
    for i, c in enumerate(s):
        if c in '([{':
            stack.append((c, i))
        elif c in ')]}':
            if not stack or '([{'.index(stack[-1][0]) != ')]}'.index(c):
                return i
            stack.pop()
    return stack[0][1] if stack else -1
