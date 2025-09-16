# Deploy new OwnerProxy
# done at 0x768caA20Cf1921772B6F56950e23Bafd94aF5CFF

from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option

# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


OWNERSHIP_ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"
PARAMETER_ADMIN = "0x4EEb3bA4f221cA16ed4A0cC7254E2E32DF948c5f"
EMERGENCY_ADMIN = "0x467947EE34aF926cF1DCac093870f613C96B1E0c"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SWAP_FACTORY = "0x4F8846Ae9380B90d2E71D5e3D042dff3E7ebb40d"


@click.group()
def cli():
    """
    Script for deploying new OwnerProxy
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    account = accounts.load("babe")
    account.set_autosign(True)

    max_fee = networks.active_provider.base_fee * 2
    max_priority_fee = int(0.5e9)
    kw = {"max_fee": max_fee, "max_priority_fee": max_priority_fee}

    with accounts.use_sender(account):
        owner_proxy = account.deploy(
            project.OwnerProxy,
            OWNERSHIP_ADMIN,
            PARAMETER_ADMIN,
            EMERGENCY_ADMIN,
            SWAP_FACTORY,
            ZERO_ADDRESS,
            **kw,
        )

    print("OwnerProxy:", owner_proxy)
