from ape import project, accounts, networks, api
from ape.cli import NetworkBoundCommand, network_option
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))

DEPLOYED_AMM = "0x7624C0DD4f5D06d650DDFF25fFEC45D032501260"
DEPLOYED_CONTROLLER = "0x80333bd8791Fee04C4C3e1CA8a524CEfA7C94737"


def deploy_blueprint(contract, account, just_bytecode=False, **kw):
    initcode = contract.contract_type.deployment_bytecode.bytecode
    if isinstance(initcode, str):
        initcode = bytes.fromhex(initcode.removeprefix("0x"))
    initcode = b"\xfe\x71\x00" + initcode  # eip-5202 preamble version 0
    if just_bytecode:
        return initcode
    initcode = (
        b"\x61" + len(initcode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + initcode
    )
    if not kw:
        kw = {'gas_price': project.provider.gas_price}
    tx = project.provider.network.ecosystem.create_transaction(
        chain_id=project.provider.chain_id,
        data=initcode,
        nonce=account.nonce,
        **kw
    )
    receipt = account.call(tx)
    click.echo(f"blueprint deployed at: {receipt.contract_address}")
    return receipt.contract_address


@click.group()
def cli():
    """
    Script for deploying new AMM and Controller implementations
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    account = accounts.load('babe')
    account.set_autosign(True)

    max_fee = networks.active_provider.base_fee * 2
    max_priority_fee = int(0.5e9)
    kw = {'max_fee': max_fee, 'max_priority_fee': max_priority_fee}

    with accounts.use_sender(account):
        controller_impl = deploy_blueprint(project.Controller, account, **kw)
        amm_impl = deploy_blueprint(project.AMM, account, **kw)

    print()

    print('Controller implementation:', controller_impl)
    print('AMM implementation:', amm_impl)


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def verify(network):
    controller_bytes = api.Address(DEPLOYED_CONTROLLER).code
    amm_bytes = api.Address(DEPLOYED_AMM).code
    assert controller_bytes == deploy_blueprint(project.Controller, None, just_bytecode=True)
    assert amm_bytes == deploy_blueprint(project.AMM, None, just_bytecode=True)
    print('Blueprints match the ones deployed on chain')
