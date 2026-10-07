from typing import List


def below_zero(operations: List[int]) -> bool:
    """ You're given a list of deposit and withdrawal operations on a bank account that starts with
    zero balance. Your task is to detect if at any point the balance of account fallls below zero, and
    at that point function should return True. Otherwise it should return False.
    >>> below_zero([1, 2, 3])
    False
    >>> below_zero([1, 2, -4, 5])
    True
    """
    balance = 0

    for op in operations:
        balance += op
        if balance < 0:
            return True

    return False


# You are given a list of transactions where each transaction is a list of deposit and withdrawal operations on multiple bank accounts. Each sublist represents the operations for a single account, and the accounts are processed in the order they appear in the main list. Your task is to determine if any account falls below zero at any point during its operations. If any account falls below zero, the function should return True. Otherwise, it should return False.
from typing import List

def below_zero(operations: List[int]) -> bool:
    balance = 0
    for op in operations:
        balance += op
        if balance < 0:
            return True
    return False

def any_account_below_zero(transactions: List[List[int]]) -> bool:
    for account in transactions:
        if below_zero(account):
            return True
    return False
