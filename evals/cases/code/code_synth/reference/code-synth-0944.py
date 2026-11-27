# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_program(tokens):
    st = []
    for t in tokens:
        if isinstance(t, int):
            st.append(t)
        if t == 'add':
            if len(st) > 1:
                b = st.pop()
                st[-1] += b
        elif t == 'over':
            if len(st) > 1:
                st.append(st[-2])
        elif t == 'dup':
            if st:
                st.append(st[-1])
        elif t == 'swap':
            if len(st) > 1:
                st[-1], st[-2] = st[-2], st[-1]
    return st
