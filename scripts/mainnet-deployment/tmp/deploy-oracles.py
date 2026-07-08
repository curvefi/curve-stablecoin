#!/usr/bin/env python3
"""
Dry-run (fork) deployment of the v2 oracle stack for lending markets.

For each market this simulates, against a mainnet fork:
    1. OracleFromCurvePools([pool], [borrowed_idx], [collateral_idx])
       -> price of the collateral's underlying in the borrowed token.
    2. (optional) the vault adapter, when the vault does not natively expose
       ERC4626 `convertToAssets` (e.g. syrupUSDC needs SyrupUSDCAdapter).
    3. ERC4626EMAWrapper(pool_oracle, vault_or_adapter, ema_time)
       -> multiplies by the EMA-dampened vault share price.

Nothing is broadcast: this only runs inside `boa.fork(...)` to validate that
the stack deploys and reports a sane `price()`.  Run with:

    MAINNET_RPC_URL=... python scripts/mainnet-deployment/tmp/deploy-oracles.py
"""

import argparse
import os

import boa

MARKETS = {
    "syrupUSDC-crvUSD": {
        "pool": {
            "address": "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",  # crvUSD/USDC
            "collateral_idx": 0,
            "borrowed_idx": 1,
        },
        "vault": {
            "address": "0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b",  # syrupUSDC
            "adapter": "curve_stablecoin/price_oracles/v2/adapters/SyrupUSDCAdapter.vy",
        },
    },
    "sDOLA-crvUSD": {
        "pool": {
            "address": "0x76A962BA6770068bCF454D34dDE17175611e6637",  # sDOLA/scrvUSD
            "collateral_idx": 1,
            "borrowed_idx": 0,
        },
        "vault": {
            "address": "0xb45ad160634c528Cc3D2926d9807104FA3157305",  # sDOLA
            "adapter": None,
        },
    },
    "sfrxUSD-crvUSD": {
        "pool": {
            "address": "0x13e12BB0E6A2f1A3d6901a59a9d585e89A6243e1",  # frxUSD/crvUSD
            "collateral_idx": 0,
            "borrowed_idx": 1,
        },
        "vault": {
            "address": "0xcf62F905562626CfcDD2261162a51fd02Fc9c5b6",  # sfrxUSD
            "adapter": None,
        },
    },
}

ORACLE_FROM_CURVE_POOLS = "curve_stablecoin/price_oracles/v2/OracleFromCurvePools.vy"
ERC4626_EMA_WRAPPER = "curve_stablecoin/price_oracles/v2/ERC4626EMAWrapper.vy"

# Placeholder EOA used inside the fork (given balance below).
DEPLOYER = "0x0000000000000000000000000000000000C0FFEE"
CHAIN_ID = 1
# Smoothing horizon of the vault-share-price EMA (seconds). 866 ~= 600s / ln(2),
# the repo's usual ~10-minute half-life convention.
DEFAULT_EMA_TIME = 866


def _deploy(deployer: str, ema_time: int) -> None:
    boa.env.eoa = deployer
    boa.env.set_balance(deployer, 10**30)

    pool_oracle_deployer = boa.load_partial(ORACLE_FROM_CURVE_POOLS)
    ema_wrapper_deployer = boa.load_partial(ERC4626_EMA_WRAPPER)

    results = {}
    for name, cfg in MARKETS.items():
        pool = cfg["pool"]
        vault = cfg["vault"]

        # 1. Curve-pool price oracle (single pool here, but the contract chains N).
        pool_oracle = pool_oracle_deployer.deploy(
            [pool["address"]],
            [pool["borrowed_idx"]],
            [pool["collateral_idx"]],
        )

        # 2. Adapter, only if the vault needs one to expose convertToAssets.
        adapter_addr = None
        if vault["adapter"]:
            adapter = boa.load_partial(vault["adapter"]).deploy()
            adapter_addr = adapter.address
            erc4626_target = adapter_addr
        else:
            erc4626_target = vault["address"]

        # 3. EMA-hardened ERC4626 wrapper = final market oracle.
        oracle = ema_wrapper_deployer.deploy(
            pool_oracle.address, erc4626_target, ema_time
        )

        price = oracle.price()  # validate it reports a sane value on the fork

        results[name] = {
            "pool_oracle": pool_oracle.address,
            "adapter": adapter_addr,
            "erc4626_target": erc4626_target,
            "oracle": oracle.address,
            "price": price,
        }
        print(
            f"[{name}] pool_oracle={pool_oracle.address} "
            f"adapter={adapter_addr} oracle={oracle.address} "
            f"price={price / 10**18:.6f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run (fork) deploy of the v2 oracle stack for lending markets"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--ema-time", type=int, default=DEFAULT_EMA_TIME)
    parser.add_argument(
        "--report-path",
        default="deployments/mainnet/oracles-dry-run.jsonc",
        help="Where to write the dry-run report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")

    with boa.fork(args.rpc_url):
        _deploy(DEPLOYER, args.ema_time)


if __name__ == "__main__":
    main()
