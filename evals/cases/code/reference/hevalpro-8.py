# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/humaneval-pro@cd078f93d57d1902b5c3e4ae330166b2ca0e0e80, item 8.
from typing import List, Tuple


def sum_product(numbers: List[int]) -> Tuple[int, int]:
    """ For a given list of integers, return a tuple consisting of a sum and a product of all the integers in a list.
    Empty sum should be equal to 0 and empty product should be equal to 1.
    >>> sum_product([])
    (0, 1)
    >>> sum_product([1, 2, 3, 4])
    (10, 24)
    """
    sum_value = 0
    prod_value = 1

    for n in numbers:
        sum_value += n
        prod_value *= n
    return sum_value, prod_value


# Given a list of lists of integers, return a list of tuples where each tuple consists of the sum and product of the integers in the corresponding sublist. Additionally, calculate the total sum and total product of all integers across all sublists.
from typing import List, Tuple


def sum_product_of_lists(lists: List[List[int]]) -> Tuple[List[Tuple[int, int]], int, int]:
    """ For a given list of lists of integers, return a list of tuples where each tuple consists of the sum and product of the integers in the corresponding sublist.
    Additionally, calculate the total sum and total product of all integers across all sublists.
    >>> sum_product_of_lists([[1, 2], [3, 4]])
    ([(3, 2), (7, 12)], 10, 24)
    """
    results = []
    total_sum = 0
    total_product = 1
    for sublist in lists:
        sub_sum, sub_product = sum_product(sublist)
        results.append((sub_sum, sub_product))
        total_sum += sub_sum
        total_product *= sub_product
    return results, total_sum, total_product
