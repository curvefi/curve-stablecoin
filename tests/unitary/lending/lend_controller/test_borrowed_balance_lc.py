import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18


def snapshot(controller, vault):
    return {
        "borrowed": controller.borrowed_balance(),
        "lent": controller.lent(),
        "repaid": controller.repaid(),
        "collected": controller.collected(),
        "deposited": vault.deposited(),
        "withdrawn": vault.withdrawn(),
    }


def expect_same(before, after, *fields):
    for field in fields:
        assert after[field] == before[field]


def test_default_behavior(controller, vault, seed_liquidity):
    state = snapshot(controller, vault)
    assert state["lent"] == 0
    assert state["collected"] == 0
    assert state["repaid"] == 0
    assert state["withdrawn"] == 0
    assert state["borrowed"] == state["deposited"] == seed_liquidity


def test_decreases_after_borrow(controller, vault, collateral_token):
    before = snapshot(controller, vault)

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address, sender=boa.env.eoa)

    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    after = snapshot(controller, vault)
    assert after["borrowed"] == before["borrowed"] - DEBT
    assert after["lent"] == before["lent"] + DEBT
    expect_same(before, after, "repaid", "collected", "deposited", "withdrawn")


def test_restores_after_repay(controller, vault, collateral_token, borrowed_token):
    before = snapshot(controller, vault)

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address, sender=boa.env.eoa)

    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    max_approve(borrowed_token, controller.address, sender=boa.env.eoa)
    controller.repay(DEBT)

    after = snapshot(controller, vault)
    expect_same(before, after, "borrowed", "collected", "deposited", "withdrawn")
    assert after["lent"] == before["lent"] + DEBT
    assert after["repaid"] == before["repaid"] + DEBT


def test_decreases_after_withdraw(
    controller,
    vault,
    collateral_token,
    borrowed_token,
):
    EXTRA_DEPOSIT = 5 * 10**18
    WITHDRAW_AMOUNT = EXTRA_DEPOSIT // 2

    start = snapshot(controller, vault)

    boa.deal(borrowed_token, boa.env.eoa, EXTRA_DEPOSIT)
    max_approve(borrowed_token, vault.address, sender=boa.env.eoa)
    assert borrowed_token.balanceOf(boa.env.eoa) == EXTRA_DEPOSIT
    vault.deposit(EXTRA_DEPOSIT)
    max_approve(borrowed_token, controller.address, sender=boa.env.eoa)

    after_deposit = snapshot(controller, vault)
    assert after_deposit["borrowed"] == start["borrowed"] + EXTRA_DEPOSIT
    assert after_deposit["deposited"] == start["deposited"] + EXTRA_DEPOSIT
    expect_same(start, after_deposit, "lent", "repaid", "collected", "withdrawn")

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address, sender=boa.env.eoa)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    after_loan = snapshot(controller, vault)
    assert after_loan["borrowed"] == after_deposit["borrowed"] - DEBT
    assert after_loan["lent"] == after_deposit["lent"] + DEBT
    expect_same(
        after_deposit, after_loan, "repaid", "collected", "deposited", "withdrawn"
    )

    controller.repay(DEBT)
    after_repay = snapshot(controller, vault)
    expect_same(
        after_deposit, after_repay, "borrowed", "collected", "deposited", "withdrawn"
    )
    expect_same(after_loan, after_repay, "lent")
    assert after_repay["repaid"] == after_deposit["repaid"] + DEBT

    withdrawn_before = vault.withdrawn()
    vault.withdraw(WITHDRAW_AMOUNT)

    after_withdraw = snapshot(controller, vault)
    assert after_withdraw["borrowed"] == after_repay["borrowed"] - WITHDRAW_AMOUNT
    assert after_withdraw["withdrawn"] == withdrawn_before + WITHDRAW_AMOUNT
    expect_same(after_repay, after_withdraw, "lent", "repaid", "collected", "deposited")


def test_collect_fees_reduces_balance(
    admin,
    controller,
    amm,
    collateral_token,
    borrowed_token,
    vault,
):
    ADMIN_FEE = WAD // 2
    RATE = 10**11
    TIME_DELTA = 86400

    before_fee = snapshot(controller, vault)
    controller.set_admin_fee(ADMIN_FEE, sender=admin)
    after_fee = snapshot(controller, vault)
    assert controller.admin_fee() == ADMIN_FEE
    assert after_fee == before_fee

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address, sender=boa.env.eoa)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    before_collect = snapshot(controller, vault)
    amm.eval(f"self.rate = {RATE}")
    amm.eval("self.rate_time = block.timestamp")
    boa.env.time_travel(TIME_DELTA)

    boa.deal(borrowed_token, controller.address, 10**24)

    amount = controller.collect_fees()

    assert amount > 0
    after_collect = snapshot(controller, vault)
    assert after_collect["collected"] == before_collect["collected"] + amount
    assert after_collect["borrowed"] == before_collect["borrowed"] - amount
    expect_same(
        before_collect, after_collect, "lent", "repaid", "deposited", "withdrawn"
    )
