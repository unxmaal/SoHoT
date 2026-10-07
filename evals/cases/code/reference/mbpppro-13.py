# Write a function to find whether a given array of integers contains any duplicate element.
def test_duplicate(arraynums):
    return len(arraynums) != len(set(arraynums))


# Given a list of arrays of integers, write a function to find whether any of these arrays contain duplicate elements. If any array contains duplicates, return a list of indices of these arrays. If no array contains duplicates, return an empty list.
def find_duplicate_arrays(arrays):
    return [i for i, array in enumerate(arrays) if test_duplicate(array)]
