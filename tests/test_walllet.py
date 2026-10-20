'''
Written by: Erick Constant
Purpose: To test the accuracy of the wallet
'''
import unittest
from unittest.mock import MagicMock
import pytest

from Wallet import *

class mockPostGresError(Exception):
    pass

def setup_postgres_mock():
    


def test_get_balance():

    assert get_balance(1) == 100
    assert get_balance(2) == 20
    

def test_transfer_money():
    assert transfer_money(1, 2, 50) == 0
    assert transfer_money(1, 10, 50) == 0
        
def test_check_for_sufficent_funds():

    assert check_for_sufficent_funds(1, 50) == True
    assert check_for_sufficent_funds(1, 150) == False
    

def test_update_money():

    assert update_money(1, 100) == "SELECT pirate_dollars FROM users WHERE id = 1"    
    assert update_money(1, 0) == 0
    



