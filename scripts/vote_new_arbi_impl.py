import sys
import boa
import os
import json
import networks
from getpass import getpass
import curve_dao
from eth_account import account
from curve_dao.addresses import CURVE_DAO_OWNERSHIP as target


FACTORY = "0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"
CONTROLLER_IMPL = "0x2287b7b2bF3d82c3ecC11ca176F4B4F35f920775"

BROADCASTER = "0xb7b0FF38E0A01D798B5cd395BbA6Ddb56A323830"
ARBI_AGENT = "0x452030a5D962d37D97A9D65487663cD5fd9C2B32"


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    boa.env.fork(networks.ARBITRUM)
    boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'

    factory = boa.from_etherscan(FACTORY, name="L2Factory", uri="https://api.arbiscan.io/api", api_key=networks.ARBISCAN_API_KEY)

    controller_impl = factory.controller_impl()
    amm_impl = factory.amm_impl()
    vault_impl = factory.vault_impl()
    pool_price_oracle_impl = factory.pool_price_oracle_impl()
    monetary_policy_impl = factory.monetary_policy_impl()
    gauge_factory = factory.gauge_factory()

    if '--fork' in sys.argv[1:]:
        boa.env.fork(networks.NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        babe = account_load('babe')
        boa.set_network_env(networks.NETWORK)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    factory_calldata = factory.set_implementations.prepare_calldata(
        CONTROLLER_IMPL,
        amm_impl,
        vault_impl,
        pool_price_oracle_impl,
        monetary_policy_impl,
        gauge_factory
    )

    arbi_actions = [
        (factory.address, factory_calldata),
    ]
    actions = [
        (BROADCASTER, 'broadcast', arbi_actions, 10_000_000, 10**9)
    ]
    vote_id = curve_dao.create_vote(
        target,
        actions,
        "Update Controller implementation for new LlamaLend markets on Arbitrum to support advanced leverage",
        networks.ETHERSCAN_API_KEY,
        networks.PINATA_TOKEN
    )
    print(vote_id)

    if '--fork' in sys.argv[1:]:
        # Simulating the vote
        assert curve_dao.simulate(vote_id, target['voting'], networks.ETHERSCAN_API_KEY)

        # Simulating the Arbitrum side
        boa.env.fork(networks.ARBITRUM)
        boa.env.eoa = BROADCASTER
        agent = boa.from_etherscan(ARBI_AGENT, name="ArbiOwnershipAgent", uri="https://api.arbiscan.io/api", api_key=networks.ARBISCAN_API_KEY)
        agent.execute(arbi_actions)

        assert CONTROLLER_IMPL == factory.controller_impl()
        assert amm_impl == factory.amm_impl()
        assert vault_impl == factory.vault_impl()
        assert pool_price_oracle_impl == factory.pool_price_oracle_impl()
        assert monetary_policy_impl == factory.monetary_policy_impl()
        assert gauge_factory == factory.gauge_factory()
