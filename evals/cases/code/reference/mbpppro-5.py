# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 5.
# Write a function to find squares of individual elements in a list.
def square_nums(nums):
 return [i**2 for i in nums]


# Given two lists of integers, write a function to find the sum of the squares of the corresponding elements in the two lists. If the lists are of different lengths, raise a ValueError.
def sum_of_squares(list1, list2):
    if len(list1) != len(list2):
        raise ValueError("Lists must be of the same length")
    squares1 = square_nums(list1)
    squares2 = square_nums(list2)
    return [x + y for x, y in zip(squares1, squares2)]
