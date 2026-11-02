"""The chart decides what may be posted to, and which side an account grows on."""

import pytest
from ledgerlite.accounts import Account, AccountType, Chart, Side
from ledgerlite.errors import DuplicateAccount, UnknownAccount


def test_an_asset_grows_on_the_debit_side():
    account = Account("1000", "Cash", AccountType.ASSET, "EUR")
    assert account.normal_side is Side.DEBIT


def test_revenue_grows_on_the_credit_side():
    account = Account("7000", "Sales", AccountType.REVENUE, "EUR")
    assert account.normal_side is Side.CREDIT


def test_the_chart_refuses_a_duplicate_code():
    chart = Chart([Account("1000", "Cash", AccountType.ASSET, "EUR")])
    with pytest.raises(DuplicateAccount):
        chart.add(Account("1000", "Petty cash", AccountType.ASSET, "EUR"))


def test_an_unknown_code_is_reported_by_name():
    chart = Chart()
    with pytest.raises(UnknownAccount):
        chart.require("9999")


def test_a_side_has_exactly_one_other_side():
    assert Side.DEBIT.other() is Side.CREDIT
    assert Side.CREDIT.other() is Side.DEBIT
