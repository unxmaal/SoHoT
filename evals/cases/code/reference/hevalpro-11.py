from typing import List


def string_xor(a: str, b: str) -> str:
    """ Input are two strings a and b consisting only of 1s and 0s.
    Perform binary XOR on these inputs and return result also as a string.
    >>> string_xor('010', '110')
    '100'
    """
    def xor(i, j):
        if i == j:
            return '0'
        else:
            return '1'

    return ''.join(xor(x, y) for x, y in zip(a, b))


# Given a list of binary strings, perform a cumulative XOR operation on them. The cumulative XOR operation means that for each string in the list, XOR it with the result of all previous XOR operations. Return the final result as a string.
from typing import List


def cumulative_xor(binary_strings: List[str]) -> str:
    """
    Given a list of binary strings, perform a cumulative XOR operation on them.
    The cumulative XOR operation means that for each string in the list, XOR it with the result of all previous XOR operations.
    Return the final result as a string.
    >>> cumulative_xor(['010', '110', '101'])
    '001'
    """
    result = binary_strings[0]
    for binary_string in binary_strings[1:]:
        result = string_xor(result, binary_string)
    return result
