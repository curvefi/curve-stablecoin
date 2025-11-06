import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEPOSIT = 10**18
DEBT = 10**18


def snapshot(controller, vault):
    return {
        "borrowed": controller.available_balance(),
        "lent": controller.lent(),
        "repaid": controller.repaid(),
        "collected": controller.collected(),
        "processed": controller.processed(),
        "asset_balance": vault.net_deposits(),
    }


def expect_same(before, after, *fields):
    for field in fields:
        assert after[field] == before[field]


def test_increases_after_deposit(controller, vault, borrowed_token):
    boa.deal(borrowed_token, boa.env.eoa, DEPOSIT)
    max_approve(borrowed_token, vault.address)

    before = snapshot(controller, vault)
    vault.deposit(DEPOSIT)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] + DEPOSIT
    assert after["asset_balance"] == before["asset_balance"] + DEBT
    expect_same(before, after, "lent", "repaid", "collected", "processed")


def test_decreases_after_withdraw(
    controller,
    vault,
    collateral_token,
    borrowed_token,
):
    boa.deal(borrowed_token, boa.env.eoa, DEPOSIT)
    max_approve(borrowed_token, vault.address)
    vault.deposit(DEPOSIT)

    before = snapshot(controller, vault)
    vault.withdraw(DEPOSIT)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - DEPOSIT
    assert after["asset_balance"] == before["asset_balance"] - DEPOSIT
    expect_same(before, after, "lent", "repaid", "collected", "processed")


def test_decreases_after_create(controller, vault, collateral_token):
    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address)

    before = snapshot(controller, vault)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - DEBT
    assert after["lent"] == before["lent"] + DEBT
    assert after["processed"] == before["processed"] + DEBT
    expect_same(before, after, "repaid", "collected", "asset_balance")


def test_decreases_after_borrow_more(controller, vault, collateral_token):
    boa.deal(collateral_token, boa.env.eoa, 2 * COLLATERAL)
    max_approve(collateral_token, controller.address)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    before = snapshot(controller, vault)
    controller.borrow_more(COLLATERAL, DEBT)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] - DEBT
    assert after["lent"] == before["lent"] + DEBT
    assert after["processed"] == before["processed"] + DEBT
    expect_same(before, after, "repaid", "collected", "asset_balance")


def test_increases_after_repay(controller, vault, collateral_token, borrowed_token):
    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address)
    max_approve(borrowed_token, controller.address)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    before = snapshot(controller, vault)
    controller.repay(DEBT)
    after = snapshot(controller, vault)

    assert after["borrowed"] == before["borrowed"] + DEBT
    assert after["repaid"] == before["repaid"] + DEBT
    expect_same(before, after, "lent", "collected", "asset_balance", "processed")


def test_collect_fees_reduces_balance(
    admin,
    controller,
    amm,
    collateral_token,
    vault,
):
    ADMIN_FEE = WAD // 2
    RATE = 10**11
    TIME_DELTA = 86400

    controller.set_admin_percentage(ADMIN_FEE, sender=admin)

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    amm.eval(f"self.rate = {RATE}")
    amm.eval("self.rate_time = block.timestamp")
    boa.env.time_travel(TIME_DELTA)

    before = snapshot(controller, vault)
    amount = controller.collect_fees()
    after = snapshot(controller, vault)

    assert amount > 0
    assert after["collected"] == before["collected"] + amount
    assert after["borrowed"] == before["borrowed"] - amount
    assert after["processed"] == after["repaid"] + controller.total_debt()
    expect_same(before, after, "lent", "repaid", "asset_balance")
