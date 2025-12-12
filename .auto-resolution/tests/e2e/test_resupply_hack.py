import boa
import pytest

from tests.utils import max_approve

# Amounts used by the attacker during the hack
DEPOSIT = 2_000_000_000_000_000_001
DONATION = 2_000 * 10**18


@pytest.fixture(scope="module")
def market_type():
    """The attach was performed on a lending market (as mint markets don't have vaults)."""
    return "lending"


def test_vault_inflation(controller, vault, borrowed_token):
    """
    Historically, vault donations could inflate `pricePerShare()` because the vault
    relied on the controller's live token balance instead of an internally tracked
    one. This quirk was safe for LlamaLend itself, yet it complicated integrations
    that plug the shares into external solvency or pricing logic. The vault now keeps
    internal accounting, so external top-ups can no longer affect later deposits and
    `pricePerShare()` stays stable, making downstream integrations easier to reason about.
    See the resupply hack postmortem for more details:
    https://mirror.xyz/0x521CB9b35514E9c8a8a929C890bf1489F63B2C84/ygJ1kh6satW9l_NDBM47V87CfaQbn2q0tWy_rtp76OI
    """
    max_approve(borrowed_token, vault)
    boa.deal(borrowed_token, boa.env.eoa, DEPOSIT)

    # Baseline without any donation
    with boa.env.anchor():
        vault.deposit(DEPOSIT)
        pps_without_donation = vault.pricePerShare()

    # Prepare balances and approvals for the real scenario
    boa.deal(borrowed_token, boa.env.eoa, DEPOSIT + DONATION)

    # Donation to the controller followed by the first valid deposit
    borrowed_token.transfer(controller, DONATION)
    vault.deposit(DEPOSIT)

    pps_with_donation = vault.pricePerShare()

    assert pps_with_donation == pps_without_donation
