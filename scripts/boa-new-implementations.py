#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"

CONTROLLER_IMPL = "0x6340678b2bab22a37d781Cd8da958a3cD1d97cdD"
AMM_IMPL = "0x3da7fF6C15C0c97D9C2dF4AF82a9910384b372FD"


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


def get_code(addr):
    return boa.env.vm.state.get_code(boa.environment.Address(addr).canonical_address)


if __name__ == '__main__':
    if '--fork' in sys.argv[1:] or '--verify' in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    controller_compiled = boa.load_partial('contracts/Controller.vy')
    amm_compiled = boa.load_partial('contracts/AMM.vy')

    controller_impl = controller_compiled.deploy_as_blueprint()
    amm_impl = amm_compiled.deploy_as_blueprint()

    if '--verify' in sys.argv[1:]:
        assert get_code(CONTROLLER_IMPL) == get_code(controller_impl.address), "Verification failed"
        assert get_code(AMM_IMPL) == get_code(amm_impl.address), "Verification failed"
        print("Implementation on chain matches local code")

    else:
        print()
        print(f'Controller implementation: {controller_impl.address}')
        print(f'AMM implementation: {amm_impl.address}')
