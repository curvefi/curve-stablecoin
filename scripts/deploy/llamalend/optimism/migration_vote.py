#!/usr/bin/env python3
"""
Create the Ownership DAO vote that moves the Optimism LlamaLend V2 markets to the
oracles and monetary policy deployed by oracles/deploy.py and
monetary_policies/wstETH-WETH/deploy.py.

The Optimism Configurator is owned by a LendingOwnerProxy whose DAO is the x-gov
ownership agent, so the vote has one action on Ethereum,
Broadcaster.broadcast(messages, gas_limit). The OP Stack messenger delivers the messages
to the Relayer, which has the agent call LendingOwnerProxy.execute(Configurator, ...):
    Configurator.set_price_oracle(controller, oracle, MAX_DEVIATION)  for each market
    Configurator.set_monetary_policy(wstETH/WETH controller, monetary_policy)
The proxy's own set_v2_price_oracle only replaces an oracle that fails, so the DAO's
execute is the path for a working one.

The whole path is simulated on forks of both chains before anything is proposed:
    1. Optimism: relay the messages through the L2 messenger from cold storage to size
       the L2 gas limit. Nothing calls the new oracles before the vote executes, so each
       is forced onto the full reseed it will take then.
    2. Ethereum: create the vote, vote yes as Convex, wait out the vote, execute it and
       capture the message the Broadcaster hands to the L1 messenger.
    3. Optimism: deliver that message through the L2 messenger as the deposit would,
       with the gas the deposit carries, and check every market.
Live, the vote is then created from the proposer's account, which needs enough veCRV
to propose.

A dry run without the deployment reports deploys the contracts on the Optimism fork
first, so the vote can be rehearsed before the real deployment.

Live needs ETHERSCAN_API_KEY and PINATA_TOKEN, a dry run only ETHERSCAN_API_KEY.

Run:
    # dry-run against forks
    OP_RPC_URL=... MAINNET_RPC_URL=... ETHERSCAN_API_KEY=... python \
scripts/deploy/llamalend/optimism/migration_vote.py --dry-run

    # propose
    OP_RPC_URL=... MAINNET_RPC_URL=... ETHERSCAN_API_KEY=... PINATA_TOKEN=... python \
scripts/deploy/llamalend/optimism/migration_vote.py --keystore <path>
"""

import argparse
import importlib.util
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import curve_dao
import requests
from boa.environment import Env
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_abi import decode, encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address


VOTE_DAO = curve_dao.DAO.OWNERSHIP
CONVEX_VOTERPROXY = "0x989AEb4d175e16225E39E87d0D97A3360524AD80"

# x-gov for Optimism: one contract is both the L1 Broadcaster and the L2 Relayer
BROADCASTER = "0x8e1e5001C7B8920196c7E3EdF2BCf47B2B6153ff"
RELAYER = "0x8e1e5001C7B8920196c7E3EdF2BCf47B2B6153ff"
OWNERSHIP_AGENT = "0x28c4A1Fa47EEE9226F8dE7D6AF0a41C62Ca98267"
L1_MESSENGER = "0x25ace71c97B33Cc4729CF772ae268934F7ab5fA1"
L2_MESSENGER = "0x4200000000000000000000000000000000000007"
# deposits arrive on L2 from the L1 messenger's aliased address
ALIASED_L1_MESSENGER = to_checksum_address(
    hex((int(L1_MESSENGER, 16) + 0x1111000000000000000000000000000000001111) % 2**160)
)

CONFIGURATOR = "0xd36c590531cAF5F620C57Faf5827Ce8E7f6E5Bec"
OWNER_PROXY = "0xeDA020b067872717901916a3B8C724C21f6080d1"  # LendingOwnerProxy
MARKET_DEPLOYMENTS = "deployments/llamalend/optimism/markets"
SCRIPTS = Path(__file__).resolve().parent
# headroom over the measured L2 gas: the reseed reads every feed round in its window,
# and a volatile market posts more of them
RELAY_GAS_MARGIN = 200_000

DESCRIPTION = (
    "Optimism LlamaLend V2: replace the ChainlinkEMA price oracles of the WBTC/USDC, "
    "wstETH/USDC and wstETH/WETH markets with the current version, which handles "
    "Chainlink aggregator upgrades, and move wstETH/WETH to HyperbolicDynamicMP with "
    "a new WstETHRateCalculator, keeping its parameters."
)


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


MESSAGES = {
    "name": "a0",
    "type": "tuple[]",
    "components": [
        {"name": "target", "type": "address"},
        {"name": "data", "type": "bytes"},
    ],
}
AGENT_ABI = boa.loads_abi(
    json.dumps(
        [
            {
                "name": "execute",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [MESSAGES],
                "outputs": [],
            }
        ]
    ),
    name="Agent",
)
CONFIGURATOR_ABI = boa.loads_abi(
    _abi(
        ("set_price_oracle", ["address", "address", "uint256"], [], "nonpayable"),
        ("set_monetary_policy", ["address", "address"], [], "nonpayable"),
        ("default_admin", [], ["address"], "view"),
    ),
    name="Configurator",
)
OWNER_PROXY_ABI = boa.loads_abi(
    _abi(
        ("execute", ["address", "bytes"], ["bytes"], "payable"),
        ("dao", [], ["address"], "view"),
        ("CONFIGURATOR", [], ["address"], "view"),
    ),
    name="LendingOwnerProxy",
)
RELAYER_ABI = boa.loads_abi(
    _abi(
        ("OWNERSHIP_AGENT", [], ["address"], "view"),
        ("MESSENGER", [], ["address"], "view"),
    ),
    name="Relayer",
)
BROADCASTER_ABI = boa.loads_abi(
    _abi(
        ("admins", [], ["address", "address", "address"], "view"),
        ("ovm_messenger", [], ["address"], "view"),
    ),
    name="Broadcaster",
)
L1_MESSENGER_ABI = boa.loads_abi(
    _abi(("baseGas", ["bytes", "uint32"], ["uint64"], "view")), name="L1Messenger"
)
L2_MESSENGER_ABI = boa.loads_abi(
    _abi(
        (
            "relayMessage",
            ["uint256", "address", "address", "uint256", "uint256", "bytes"],
            [],
            "payable",
        ),
    ),
    name="L2Messenger",
)
ORACLE_ABI = boa.loads_abi(
    _abi(
        ("storedObservationTimestamp", [], ["uint256"], "view"),
        ("OBSERVATIONS", [], ["uint256"], "view"),
        ("INTERVAL", [], ["uint256"], "view"),
    ),
    name="ChainlinkEMA",
)
CONTROLLER_ABI = boa.loads_abi(
    _abi(("monetary_policy", [], ["address"], "view")), name="Controller"
)
AMM_ABI = boa.loads_abi(
    _abi(
        ("price_oracle", [], ["uint256"], "view"),
        ("price_oracle_contract", [], ["address"], "view"),
        ("rate", [], ["uint256"], "view"),
    ),
    name="AMM",
)
MP_ABI = boa.loads_abi(_abi(("rate", [], ["uint256"], "view")), name="MonetaryPolicy")

SENT_MESSAGE = int.from_bytes(
    keccak(text="SentMessage(address,address,bytes,uint256,uint256)"), "big"
)
RELAYED_MESSAGE = int.from_bytes(keccak(text="RelayedMessage(bytes32)"), "big")
FAILED_RELAYED_MESSAGE = int.from_bytes(
    keccak(text="FailedRelayedMessage(bytes32)"), "big"
)


def _load_account(keystore_path: str) -> Account:
    """Decrypt a keystore file."""
    path = Path(keystore_path)
    with open(path) as f:
        pkey = Account.decrypt(json.load(f), getpass(f"Password for {path.name}: "))
    return Account.from_key(pkey)


class RetryRPC(EthereumRPC):
    """A fork reads every touched storage slot over RPC, so back off when rate limited.
    Live, boa re-forks at each receipt's block, which a lagging node may not have yet."""

    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(10):
            try:
                result = super().fetch(method, params)
                if result is None and method == "eth_getBlockByNumber" and attempt < 9:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                    continue
                return result
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


def _read_report(path: Path, dry_run: bool) -> dict:
    report = json.loads(path.read_text())
    assert report["chain_id"] == 10
    assert dry_run or not report["dry_run"], f"{path} is a dry run"
    return report


def _load_reports(oracles_path: Path, mp_path: Path, dry_run: bool):
    """Each report that exists is used as is; a dry run deploys only what is missing."""
    oracles_script = _load_script(SCRIPTS / "oracles" / "deploy.py")
    mp_script = _load_script(
        SCRIPTS / "monetary_policies" / "wstETH-WETH" / "deploy.py"
    )
    missing = [str(p) for p in (oracles_path, mp_path) if not p.exists()]
    if missing and not dry_run:
        raise SystemExit(f"Deployment report not found: {', '.join(missing)}")
    deployer = boa.env.generate_address("deployer")

    if oracles_path.exists():
        oracles = _read_report(oracles_path, dry_run)
        assert set(oracles["oracles"]) == set(oracles_script.MARKETS)
    else:
        print(f"{oracles_path} not found, deploying the oracles on the Optimism fork\n")
        oracles = oracles_script._deploy(deployer, True, Path(os.devnull))
        print()

    if mp_path.exists():
        mp = _read_report(mp_path, dry_run)
    else:
        print(f"{mp_path} not found, deploying the policy on the Optimism fork\n")
        mp = mp_script._deploy(
            deployer,
            True,
            Path(f"{MARKET_DEPLOYMENTS}/wstETH-WETH.jsonc"),
            Path(os.devnull),
        )
        print()
    return oracles, mp, oracles_script.MAX_DEVIATION


def _messages(oracles: dict, mp: dict, max_deviation: int) -> list:
    configurator = CONFIGURATOR_ABI.at(CONFIGURATOR)
    calls = [
        configurator.set_price_oracle.prepare_calldata(
            e["controller"], e["price_oracle"], max_deviation
        )
        for e in oracles["oracles"].values()
    ]
    calls.append(
        configurator.set_monetary_policy.prepare_calldata(
            mp["controller"], mp["monetary_policy"]
        )
    )
    proxy = OWNER_PROXY_ABI.at(OWNER_PROXY)
    return [
        (OWNER_PROXY, proxy.execute.prepare_calldata(CONFIGURATOR, call))
        for call in calls
    ]


def _relay_calldata(messages: list) -> bytes:
    # what the Broadcaster asks the L1 messenger to deliver to the Relayer
    return keccak(text="relay(uint256,(address,bytes)[])")[:4] + encode(
        ["uint256", "(address,bytes)[]"],
        [1, messages],  # the Agent enum is a vyper flag, OWNERSHIP is 1
    )


def _check_optimism_setup() -> None:
    relayer = RELAYER_ABI.at(RELAYER)
    assert relayer.OWNERSHIP_AGENT() == OWNERSHIP_AGENT
    assert relayer.MESSENGER() == L2_MESSENGER
    assert CONFIGURATOR_ABI.at(CONFIGURATOR).default_admin() == OWNER_PROXY
    proxy = OWNER_PROXY_ABI.at(OWNER_PROXY)
    assert proxy.dao() == OWNERSHIP_AGENT
    assert proxy.CONFIGURATOR() == CONFIGURATOR


def _force_reseed(oracles: dict) -> None:
    """Make each new oracle's stored observation as old as it will be at execution."""
    for entry in oracles["oracles"].values():
        oracle = ORACLE_ABI.at(entry["price_oracle"])
        interval = oracle.INTERVAL()
        current = boa.env.evm.patch.timestamp // interval * interval
        stale = current - 2 * oracle.OBSERVATIONS() * interval
        boa.env.set_storage(oracle.address, 1, stale)  # storedObservationTimestamp
        assert oracle.storedObservationTimestamp() == stale


def _find_call(computation, address: str):
    if to_checksum_address(computation.msg.code_address) == address:
        return computation
    for child in computation.children:
        found = _find_call(child, address)
        if found:
            return found
    return None


def _relay_gas(oracles: dict, messages: list) -> int:
    """Gas the Relayer's call takes, which is what the L2 gas limit has to cover."""
    # Reading reports and deploying on the fork warms storage the deposit will be the
    # first to touch, and cold reads cost ~20x more; the reset can't run inside an anchor
    boa.env.evm.reset_access_counters()
    with boa.env.anchor():
        _force_reseed(oracles)
        # any unused nonce, version 1; no gas floor, the relay just has to succeed
        computation = _deliver(1 << 240, _relay_calldata(messages), 0, 30_000_000)
        return _find_call(computation, RELAYER).get_gas_used()


def _create_vote(
    messages: list, gas_limit: int, dry_run: bool, etherscan_api_key, pinata_token
) -> int:
    return curve_dao.create_vote(
        VOTE_DAO,
        [(BROADCASTER, "broadcast", messages, gas_limit)],
        DESCRIPTION,
        etherscan_api_key=etherscan_api_key,
        pinata_token=pinata_token,
        is_simulation=dry_run,
    )


def _execute_vote(vote_id: int, etherscan_api_key: str) -> tuple:
    """Pass and execute the vote on the fork, as curve_dao.simulate does, and return
    the message the L1 messenger sent."""
    dao = curve_dao.get_dao_parameters(VOTE_DAO)
    voting = boa.from_etherscan(
        dao["voting"], name="AragonVoting", api_key=etherscan_api_key
    )
    with boa.env.prank(CONVEX_VOTERPROXY):
        voting.vote(vote_id, True, False)
    boa.env.time_travel(seconds=voting.voteTime())
    assert voting.canExecute(vote_id)
    voting.executeVote(vote_id, sender=boa.env.generate_address("executor"))

    sent = []
    for _, address, topics, data in voting._computation.get_raw_log_entries():
        if to_checksum_address(address) == L1_MESSENGER and topics[0] == SENT_MESSAGE:
            target = to_checksum_address(topics[1].to_bytes(32, "big")[12:])
            sender, message, nonce, gas_limit = decode(
                ["address", "bytes", "uint256", "uint256"], data
            )
            sent.append(
                (target, to_checksum_address(sender), message, nonce, gas_limit)
            )
    assert len(sent) == 1, f"expected one L1 message, got {len(sent)}"
    return sent[0]


def _deliver(nonce: int, message: bytes, gas_limit: int, deposit_gas: int):
    l2_messenger = L2_MESSENGER_ABI.at(L2_MESSENGER)
    l2_messenger.relayMessage(
        nonce,
        BROADCASTER,
        RELAYER,
        0,
        gas_limit,
        message,
        sender=ALIASED_L1_MESSENGER,
        gas=deposit_gas,
    )
    # the L2 messenger records a failed call instead of reverting
    events = [t[0] for _, _, t, _ in l2_messenger._computation.get_raw_log_entries()]
    assert FAILED_RELAYED_MESSAGE not in events, "relay failed on L2"
    assert RELAYED_MESSAGE in events, "message not relayed"
    return l2_messenger._computation


def _amm(market: str):
    existing = json.loads(Path(f"{MARKET_DEPLOYMENTS}/{market}.jsonc").read_text())
    return AMM_ABI.at(existing["amm"])


def _check_markets(oracles: dict, mp: dict, before: dict, max_deviation: int) -> None:
    for market, entry in oracles["oracles"].items():
        amm = _amm(market)
        assert amm.price_oracle_contract() == entry["price_oracle"], market
        after = amm.price_oracle()
        deviation = abs(after - before[market]) * 10**18 // before[market]
        assert deviation <= max_deviation, market
        print(
            f"  {market}: oracle {entry['price_oracle']}, price {before[market]} -> "
            f"{after} ({deviation / 1e16:.4f}%)"
        )
    controller = CONTROLLER_ABI.at(mp["controller"])
    assert controller.monetary_policy() == mp["monetary_policy"]
    amm = _amm("wstETH-WETH")
    rate = MP_ABI.at(mp["monetary_policy"]).rate()
    assert amm.rate() == rate
    print(
        f"  wstETH-WETH: policy {mp['monetary_policy']}, "
        f"rate {rate * 365 * 86400 / 1e16:.2f}% APR"
    )


def _check_ethereum_setup(proposer: str | None, etherscan_api_key: str) -> None:
    broadcaster = BROADCASTER_ABI.at(BROADCASTER)
    dao = curve_dao.get_dao_parameters(VOTE_DAO)
    assert broadcaster.admins()[0] == to_checksum_address(dao["agent"])
    assert broadcaster.ovm_messenger() == L1_MESSENGER
    if proposer:
        voting = boa.from_etherscan(
            dao["voting"], name="AragonVoting", api_key=etherscan_api_key
        )
        assert voting.canCreateNewVote(proposer), "proposer cannot create a vote"


def simulate(op_env, eth_env, args, proposer: str | None) -> tuple:
    with boa.swap_env(op_env):
        print(f"Optimism fork block: {boa.env.evm.patch.block_number}")
        oracles, mp, max_deviation = _load_reports(
            Path(args.oracles_report), Path(args.monetary_policy_report), args.dry_run
        )
        _check_optimism_setup()
        messages = _messages(oracles, mp, max_deviation)
        gas_used = _relay_gas(oracles, messages)
        gas_limit = gas_used + RELAY_GAS_MARGIN
        print(f"L2 gas: {gas_used} measured, limit {gas_limit}")

    with boa.swap_env(eth_env):
        print(f"Ethereum fork block: {boa.env.evm.patch.block_number}")
        _check_ethereum_setup(proposer, args.etherscan_api_key)
        boa.env.eoa = proposer or CONVEX_VOTERPROXY
        vote_id = _create_vote(messages, gas_limit, True, args.etherscan_api_key, None)
        target, sender, message, nonce, sent_gas_limit = _execute_vote(
            vote_id, args.etherscan_api_key
        )
        assert (target, sender) == (RELAYER, BROADCASTER)
        assert sent_gas_limit == gas_limit
        assert message == _relay_calldata(messages), "broadcast message differs"
        deposit_gas = L1_MESSENGER_ABI.at(L1_MESSENGER).baseGas(message, gas_limit)
        print(f"Vote {vote_id} executed on the fork, deposit gas {deposit_gas}")

    with boa.swap_env(op_env):
        before = {market: _amm(market).price_oracle() for market in oracles["oracles"]}
        boa.env.evm.reset_access_counters()
        _force_reseed(oracles)
        _deliver(nonce, message, gas_limit, deposit_gas)
        print("Delivered on the Optimism fork:")
        _check_markets(oracles, mp, before, max_deviation)

    return messages, gas_limit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the vote moving the OP LlamaLend markets to the new oracles and policy"
    )
    parser.add_argument("--op-rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--eth-rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("PROPOSER_KEYSTORE"),
        help="Path to the proposer's keystore JSON file (optional for a dry run)",
    )
    parser.add_argument(
        "--etherscan-api-key", default=os.environ.get("ETHERSCAN_API_KEY")
    )
    parser.add_argument("--pinata-token", default=os.environ.get("PINATA_TOKEN"))
    parser.add_argument(
        "--oracles-report", default="deployments/llamalend/optimism/oracles.jsonc"
    )
    parser.add_argument(
        "--monetary-policy-report",
        default="deployments/llamalend/optimism/monetary_policies/wstETH-WETH.jsonc",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend/optimism/migration_vote.jsonc",
        help="Where to write the vote report",
    )
    args = parser.parse_args()

    if not args.op_rpc_url:
        raise SystemExit("Missing --op-rpc-url or OP_RPC_URL")
    if not args.eth_rpc_url:
        raise SystemExit("Missing --eth-rpc-url or MAINNET_RPC_URL")
    if not args.etherscan_api_key:
        raise SystemExit("Missing --etherscan-api-key or ETHERSCAN_API_KEY")
    report_path = Path(args.report_path)
    if not args.dry_run:
        if not args.keystore:
            raise SystemExit("Missing --keystore or PROPOSER_KEYSTORE")
        if not args.pinata_token:
            raise SystemExit("Missing --pinata-token or PINATA_TOKEN")
        if report_path.exists():
            raise SystemExit(f"Vote report already exists: {report_path}")

    acct = _load_account(args.keystore) if args.keystore else None
    proposer = acct.address if acct else None

    op_env = Env()
    op_env.fork_rpc(RetryRPC(args.op_rpc_url))
    eth_env = Env()
    eth_env.fork_rpc(RetryRPC(args.eth_rpc_url))
    messages, gas_limit = simulate(op_env, eth_env, args, proposer)

    print(f"\nBroadcaster {BROADCASTER} broadcast(messages, {gas_limit}):")
    for target, calldata in messages:
        print(f"  {target} 0x{calldata.hex()}")
    if args.dry_run:
        print("\nDry run, no vote created")
        return

    with boa.set_env(NetworkEnv(RetryRPC(args.eth_rpc_url))):
        boa.env.add_account(acct, force_eoa=True)
        # a failed trace would raise after the vote is mined, before the report is written
        boa.env.suppress_debug_tt()
        vote_id = _create_vote(
            messages, gas_limit, False, args.etherscan_api_key, args.pinata_token
        )
    report = {
        "chain_id": 1,
        "dao": str(VOTE_DAO),
        "vote_id": vote_id,
        "proposer": proposer,
        "timestamp": int(time.time()),
        "description": DESCRIPTION,
        "broadcaster": BROADCASTER,
        "gas_limit": gas_limit,
        "messages": [
            {"target": target, "calldata": "0x" + calldata.hex()}
            for target, calldata in messages
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    print(f"\nVote {vote_id} created, report: {report_path}")


if __name__ == "__main__":
    main()
