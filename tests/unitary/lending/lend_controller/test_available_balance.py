import boa
import pytest
from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD


@pytest.fixture(scope="module")
def amounts(collateral_token, borrowed_token):
    return {
        "collateral": int(1000 * 10 ** collateral_token.decimals()),
        "deposit": int(10 ** borrowed_token.decimals()),
        "debt": int(10 ** borrowed_token.decimals()),
    }


def snapshot(controller, vault):
    return {
        "borrowed": controller.available_balance(),
        "lent": controller.lent(),
        "repaid": controller.repaid(),
        "collected": controller.collected(),
        "asset_balance": vault.net_deposits(),
    }


def expect_same(before, after, *fields):
    for field in fields:
        assert after[field] == before[field]


def test_increases_after_deposit(controller, vault, borrowed_token, amounts):
    boa.deal(borrowed_token, boa.env.eoa, amounts["deposit"])
    max_approve(borrowed_token, vault.address)

    before = snapshot(controller, vault)
    vault.deposit(amounts["deposit"])
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] + amounts["deposit"]
    assert after["asset_balance"] == before["asset_balance"] + amounts["debt"]
    expect_same(before, after, "lent", "repaid", "collected")


def test_decreases_after_withdraw(
    controller,
    vault,
    collateral_token,
    borrowed_token,
    amounts,
):
    boa.deal(borrowed_token, boa.env.eoa, amounts["deposit"])
    max_approve(borrowed_token, vault.address)
    vault.deposit(amounts["deposit"])

    before = snapshot(controller, vault)
    vault.withdraw(amounts["deposit"])
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - amounts["deposit"]
    assert after["asset_balance"] == before["asset_balance"] - amounts["deposit"]
    expect_same(before, after, "lent", "repaid", "collected")


def test_decreases_after_create(controller, vault, collateral_token, amounts):
    boa.deal(collateral_token, boa.env.eoa, amounts["collateral"])
    max_approve(collateral_token, controller.address)

    before = snapshot(controller, vault)
    controller.create_loan(amounts["collateral"], amounts["debt"], MIN_TICKS)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - amounts["debt"]
    assert after["lent"] == before["lent"] + amounts["debt"]
    expect_same(before, after, "repaid", "collected", "asset_balance")


def test_decreases_after_borrow_more(controller, vault, collateral_token, amounts):
    boa.deal(collateral_token, boa.env.eoa, 2 * amounts["collateral"])
    max_approve(collateral_token, controller.address)
    controller.create_loan(amounts["collateral"], amounts["debt"], MIN_TICKS)

    before = snapshot(controller, vault)
    controller.borrow_more(amounts["collateral"], amounts["debt"])
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - amounts["debt"]
    assert after["lent"] == before["lent"] + amounts["debt"]
    expect_same(before, after, "repaid", "collected", "asset_balance")


def test_increases_after_repay(
    controller, vault, collateral_token, borrowed_token, amounts
):
    boa.deal(collateral_token, boa.env.eoa, amounts["collateral"])
    max_approve(collateral_token, controller.address)
    max_approve(borrowed_token, controller.address)
    controller.create_loan(amounts["collateral"], amounts["debt"], MIN_TICKS)

    before = snapshot(controller, vault)
    controller.repay(amounts["debt"])
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] + amounts["debt"]
    assert after["repaid"] == before["repaid"] + amounts["debt"]
    expect_same(before, after, "lent", "collected", "asset_balance")


def test_collect_fees_reduces_balance(
    admin,
    controller,
    amm,
    collateral_token,
    vault,
    amounts,
):
    ADMIN_FEE = WAD // 2
    RATE = 10**11
    TIME_DELTA = 180 * 86400

    controller.set_admin_percentage(ADMIN_FEE, sender=admin)

    boa.deal(collateral_token, boa.env.eoa, amounts["collateral"])
    max_approve(collateral_token, controller.address)
    controller.create_loan(amounts["collateral"], amounts["debt"], MIN_TICKS)

    amm.eval(f"self.rate = {RATE}")
    amm.eval("self.rate_time = block.timestamp")
    boa.env.time_travel(TIME_DELTA)

    before = snapshot(controller, vault)
    amount = controller.collect_fees()
    after = snapshot(controller, vault)

    assert amount > 0
    assert after["collected"] == before["collected"] + amount
    assert after["borrowed"] == before["borrowed"] - amount
    expect_same(before, after, "lent", "repaid", "asset_balance")
