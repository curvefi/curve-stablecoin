#!/usr/bin/env python3
"""
Rehearse the Optimism LlamaLend V2 migration on a fork, before the DAO vote.

    1. Deploy the replacement ChainlinkEMA oracles and the wstETH/WETH monetary policy,
       using oracles/deploy.py and monetary_policies/wstETH-WETH/deploy.py.
    2. Run the governance actions as the ownership agent, the Configurator's
       default_admin: set_price_oracle for each market and set_monetary_policy for
       wstETH/WETH. Their calldata is printed for the vote.
    3. Check every market is bound to the new contracts, prices are unchanged and the
       rate was updated.
    4. Exercise each market: deposit, create_loan, borrow_more, add_collateral, an AMM
       exchange (which calls price_w), partial and full repay, then a liquidation once
       accrued interest makes a max-size loan unhealthy.

Run:
    OP_RPC_URL=... python scripts/deploy/llamalend/optimism/rehearse_migration.py
"""

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import boa
import requests
from boa.environment import Env
from boa.rpc import EthereumRPC
from eth_utils import keccak


OWNERSHIP_AGENT = "0x28c4A1Fa47EEE9226F8dE7D6AF0a41C62Ca98267"
CONFIGURATOR = "0xd36c590531cAF5F620C57Faf5827Ce8E7f6E5Bec"
MARKET_DEPLOYMENTS = "deployments/llamalend/optimism/markets"
SCRIPTS = Path(__file__).resolve().parent
N_BANDS = 10
MAX_UINT = 2**256 - 1

# collateral per test loan, in the collateral token's units
COLLATERAL_AMOUNT = {
    "WBTC-USDC": 10**7,  # 0.1 WBTC
    "wstETH-USDC": 2 * 10**18,
    "wstETH-WETH": 2 * 10**18,
}


def _abi(*entries):
    out = []
    for name, inputs, outputs, mutability in entries:
        out.append(
            {
                "name": name,
                "type": "function",
                "stateMutability": mutability,
                "inputs": [{"name": f"a{i}", "type": t} for i, t in enumerate(inputs)],
                "outputs": [{"name": "", "type": t} for t in outputs],
            }
        )
    return json.dumps(out)


CONFIGURATOR_ABI = boa.loads_abi(
    _abi(
        ("set_price_oracle", ["address", "address", "uint256"], [], "nonpayable"),
        ("set_monetary_policy", ["address", "address"], [], "nonpayable"),
        ("default_admin", [], ["address"], "view"),
    ),
    name="Configurator",
)
CONTROLLER_ABI = boa.loads_abi(
    _abi(
        ("create_loan", ["uint256", "uint256", "uint256"], [], "nonpayable"),
        ("borrow_more", ["uint256", "uint256"], [], "nonpayable"),
        ("add_collateral", ["uint256"], [], "nonpayable"),
        ("repay", ["uint256"], [], "nonpayable"),
        ("liquidate", ["address", "uint256"], [], "nonpayable"),
        ("health", ["address", "bool"], ["int256"], "view"),
        ("debt", ["address"], ["uint256"], "view"),
        ("loan_exists", ["address"], ["bool"], "view"),
        ("max_borrowable", ["uint256", "uint256"], ["uint256"], "view"),
        ("monetary_policy", [], ["address"], "view"),
        ("borrowed_token", [], ["address"], "view"),
        ("collateral_token", [], ["address"], "view"),
    ),
    name="Controller",
)
AMM_ABI = boa.loads_abi(
    _abi(
        (
            "exchange",
            ["uint256", "uint256", "uint256", "uint256"],
            ["uint256[2]"],
            "nonpayable",
        ),
        ("rate", [], ["uint256"], "view"),
        ("price_oracle", [], ["uint256"], "view"),
        ("price_oracle_contract", [], ["address"], "view"),
    ),
    name="AMM",
)
VAULT_ABI = boa.loads_abi(
    _abi(("deposit", ["uint256"], ["uint256"], "nonpayable")), name="Vault"
)
ERC20_ABI = boa.loads_abi(
    _abi(
        ("balanceOf", ["address"], ["uint256"], "view"),
        ("approve", ["address", "uint256"], ["bool"], "nonpayable"),
        ("decimals", [], ["uint8"], "view"),
    ),
    name="ERC20",
)
MP_ABI = boa.loads_abi(_abi(("rate", [], ["uint256"], "view")), name="MonetaryPolicy")


class RetryRPC(EthereumRPC):
    """A fork reads every touched storage slot over RPC; back off when rate limited."""

    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(10):
            try:
                return super().fetch(method, params)
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status not in (429, 503) or attempt == 9:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 30)


def _load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deal(token, to: str, amount: int) -> None:
    """Set an ERC20 balance on the fork by finding its balance mapping slot."""
    holder = bytes.fromhex(to[2:].rjust(64, "0"))
    for slot in range(64):
        s = slot.to_bytes(32, "big")
        for key in (keccak(holder + s), keccak(s + holder)):  # solidity, vyper layout
            k = int.from_bytes(key, "big")
            before = boa.env.get_storage(token.address, k)
            boa.env.set_storage(token.address, k, amount)
            if token.balanceOf(to) == amount:
                return
            boa.env.set_storage(token.address, k, before)
    raise RuntimeError(f"balance slot not found for {token.address}")


def _check(results: list, label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok))
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def _market_contracts(market: str) -> dict:
    existing = json.loads(Path(f"{MARKET_DEPLOYMENTS}/{market}.jsonc").read_text())
    ctrl = CONTROLLER_ABI.at(existing["controller"])
    return {
        "controller": ctrl,
        "amm": AMM_ABI.at(existing["amm"]),
        "vault": VAULT_ABI.at(existing["vault"]),
        "borrowed": ERC20_ABI.at(ctrl.borrowed_token()),
        "collateral": ERC20_ABI.at(ctrl.collateral_token()),
    }


def _provide_liquidity(market: str, m: dict) -> None:
    # max_borrowable is capped by the vault's free liquidity, which is thin on these
    # markets, so deposit enough for the test loans first: twice the collateral value
    c = COLLATERAL_AMOUNT[market]
    c_dec, b_dec = m["collateral"].decimals(), m["borrowed"].decimals()
    value = (
        c * 10 ** (18 - c_dec) * m["amm"].price_oracle() // 10**18 // 10 ** (18 - b_dec)
    )
    lender = boa.env.generate_address(f"{market}-lender")
    _deal(m["borrowed"], lender, 2 * value)
    with boa.env.prank(lender):
        m["borrowed"].approve(m["vault"].address, MAX_UINT)
        m["vault"].deposit(2 * value)


def _exercise(market: str, m: dict, results: list) -> None:
    ctrl, amm, borrowed, collateral = (
        m["controller"],
        m["amm"],
        m["borrowed"],
        m["collateral"],
    )
    c = COLLATERAL_AMOUNT[market]
    _provide_liquidity(market, m)
    max_debt = ctrl.max_borrowable(c, N_BANDS)

    user = boa.env.generate_address(f"{market}-user")
    _deal(collateral, user, 2 * c)
    _deal(borrowed, user, 2 * max_debt)
    with boa.env.prank(user):
        collateral.approve(ctrl.address, MAX_UINT)
        borrowed.approve(ctrl.address, MAX_UINT)

        debt = max_debt // 2
        ctrl.create_loan(c, debt, N_BANDS)
        _check(
            results, f"{market}: create_loan", ctrl.loan_exists(user), f"debt {debt}"
        )

        ctrl.borrow_more(c // 2, debt // 4)
        ctrl.add_collateral(c // 4)
        _check(
            results,
            f"{market}: borrow_more + add_collateral",
            ctrl.health(user, True) > 0,
        )

    swapper = boa.env.generate_address(f"{market}-swapper")
    amm.exchange(0, 1, 0, 0, sender=swapper)  # zero-size exchange still runs price_w
    _deal(borrowed, swapper, max_debt // 100)
    with boa.env.prank(swapper):
        borrowed.approve(amm.address, MAX_UINT)
        amount_in, amount_out = amm.exchange(0, 1, max_debt // 100, 0)
    _check(
        results,
        f"{market}: AMM exchange",
        collateral.balanceOf(swapper) == amount_out,
        f"{amount_in} borrowed in, {amount_out} collateral out",
    )

    with boa.env.prank(user):
        before = ctrl.debt(user)
        ctrl.repay(before // 3)
        _check(results, f"{market}: partial repay", ctrl.debt(user) < before)
        ctrl.repay(MAX_UINT)
        _check(results, f"{market}: full repay", not ctrl.loan_exists(user))


def _open_max_loan(market: str, m: dict) -> str:
    ctrl, collateral = m["controller"], m["collateral"]
    c = COLLATERAL_AMOUNT[market]
    _provide_liquidity(market, m)
    borrower = boa.env.generate_address(f"{market}-max-borrower")
    _deal(collateral, borrower, c)
    with boa.env.prank(borrower):
        collateral.approve(ctrl.address, MAX_UINT)
        ctrl.create_loan(c, ctrl.max_borrowable(c, N_BANDS) * 999 // 1000, N_BANDS)
    return borrower


def _liquidate(market: str, m: dict, borrower: str, results: list) -> None:
    ctrl, borrowed = m["controller"], m["borrowed"]
    liquidator = boa.env.generate_address(f"{market}-liquidator")
    _deal(borrowed, liquidator, 2 * ctrl.debt(borrower))
    with boa.env.prank(liquidator):
        borrowed.approve(ctrl.address, MAX_UINT)
        ctrl.liquidate(borrower, 0)
    _check(results, f"{market}: liquidate", not ctrl.loan_exists(borrower))


def rehearse() -> list:
    results = []
    oracles_script = _load_script(SCRIPTS / "oracles" / "deploy.py")
    mp_script = _load_script(
        SCRIPTS / "monetary_policies" / "wstETH-WETH" / "deploy.py"
    )
    markets = oracles_script.MARKETS
    contracts = {market: _market_contracts(market) for market in markets}
    before = {market: m["amm"].price_oracle() for market, m in contracts.items()}

    print("=== 1. Deploy")
    deployer = boa.env.generate_address("deployer")
    oracles = oracles_script._deploy(deployer, True, Path(os.devnull))
    mp = mp_script._deploy(
        deployer,
        True,
        Path(f"{MARKET_DEPLOYMENTS}/wstETH-WETH.jsonc"),
        Path(os.devnull),
    )

    print("\n=== 2. Governance actions as the ownership agent")
    configurator = CONFIGURATOR_ABI.at(CONFIGURATOR)
    _check(
        results,
        "agent is the Configurator default_admin",
        configurator.default_admin() == OWNERSHIP_AGENT,
    )
    actions = [
        (
            configurator.set_price_oracle,
            (e["controller"], e["price_oracle"], oracles_script.MAX_DEVIATION),
        )
        for e in oracles["oracles"].values()
    ] + [(configurator.set_monetary_policy, (mp["controller"], mp["monetary_policy"]))]
    for fn, args in actions:
        print(f"  {CONFIGURATOR} {fn.name}{args}")
        print(f"    calldata: 0x{fn.prepare_calldata(*args).hex()}")
        fn(*args, sender=OWNERSHIP_AGENT)

    print("\n=== 3. Bindings")
    for market, m in contracts.items():
        new_oracle = oracles["oracles"][market]["price_oracle"]
        _check(
            results,
            f"{market}: AMM uses the new oracle",
            m["amm"].price_oracle_contract() == new_oracle,
        )
        after = m["amm"].price_oracle()
        _check(
            results,
            f"{market}: price_oracle unchanged",
            after == before[market],
            f"{before[market]} -> {after}",
        )
    ctrl = contracts["wstETH-WETH"]["controller"]
    _check(
        results,
        "wstETH-WETH: controller uses the new policy",
        ctrl.monetary_policy() == mp["monetary_policy"],
    )
    amm_rate = contracts["wstETH-WETH"]["amm"].rate()
    mp_rate = MP_ABI.at(mp["monetary_policy"]).rate()
    _check(
        results,
        "wstETH-WETH: AMM rate set from the new policy",
        amm_rate == mp_rate,
        f"{amm_rate * 365 * 86400 / 1e16:.2f}% APR",
    )

    print("\n=== 4. Market operations")
    for market, m in contracts.items():
        _exercise(market, m, results)

    print("\n=== 5. Liquidation after interest accrues")
    # a max-size loan starts a few percent healthy, so it takes years of interest at
    # low rates; each one is liquidated as soon as it turns unhealthy
    borrowers = {market: _open_max_loan(market, m) for market, m in contracts.items()}
    for market, m in contracts.items():
        health = m["controller"].health(borrowers[market], True)
        rate = m["amm"].rate() * 365 * 86400 / 1e16
        print(f"  {market}: max loan health {health / 1e16:.2f}%, rate {rate:.2f}% APR")
    for step in range(1, 201):
        boa.env.time_travel(seconds=90 * 86400)
        for market in list(borrowers):
            m = contracts[market]
            if m["controller"].health(borrowers[market], True) < 0:
                print(f"  {market}: unhealthy after ~{step * 90} days")
                _liquidate(market, m, borrowers.pop(market), results)
        if not borrowers:
            break
    for market in borrowers:
        _check(results, f"{market}: liquidate", False, "still healthy after 50 years")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rehearse the Optimism LlamaLend migration on a fork"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    args = parser.parse_args()
    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    env = Env()
    env.fork_rpc(RetryRPC(args.rpc_url))
    with boa.swap_env(env):
        print(f"Fork block: {boa.env.evm.patch.block_number}\n")
        results = rehearse()

    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        raise SystemExit("FAILED: " + "; ".join(failed))


if __name__ == "__main__":
    main()
