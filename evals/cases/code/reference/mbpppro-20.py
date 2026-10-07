# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 20.
# Write a python function to find smallest number in a list.
def smallest_num(xs):
  assert len(xs) > 0, "invalid inputs"
  return min(xs)


# Write a Python function to find the smallest number in each sublist of a list of lists, and then return the smallest number among these smallest numbers.
def smallest_in_sublists(list_of_lists):
  assert len(list_of_lists) > 0, "invalid inputs"
  smallest_numbers = [smallest_num(sublist) for sublist in list_of_lists]
  return smallest_num(smallest_numbers)
