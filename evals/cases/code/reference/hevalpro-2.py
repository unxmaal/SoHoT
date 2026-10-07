

def truncate_number(number: float) -> float:
    """ Given a positive floating point number, it can be decomposed into
    and integer part (largest integer smaller than given number) and decimals
    (leftover part always smaller than 1).

    Return the decimal part of the number.
    >>> truncate_number(3.5)
    0.5
    """
    return number % 1.0


# Given a list of positive floating point numbers, decompose each number into its integer part and decimal part. Then, calculate the sum of all the integer parts and the sum of all the decimal parts separately. Finally, return the product of these two sums.
import math
def sum_of_parts(numbers: list) -> float:
    integer_sum = 0
    decimal_sum = 0
    for number in numbers:
        decimal_part = truncate_number(number)
        integer_part = number - decimal_part
        integer_sum += integer_part
        decimal_sum += decimal_part
    return integer_sum * decimal_sum
