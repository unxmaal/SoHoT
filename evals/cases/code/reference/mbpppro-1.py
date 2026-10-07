# Write a python function to identify non-prime numbers.
import math
def is_not_prime(n):
    if n == 1:
        return True
    for i in range(2, int(math.sqrt(n))+1):
        if n % i == 0:
            return True
    return False


# Write a Python function to identify the first N non-prime numbers in a given range [start, end]. If the count of non-prime numbers in the range is less than N, return all non-prime numbers found.

def first_n_non_primes(start, end, N):
    non_primes = []
    for num in range(start, end + 1):
        if is_not_prime(num):
            non_primes.append(num)
        if len(non_primes) == N:
            break
    return non_primes
