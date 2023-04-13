from ape import Contract, Project
from ape.contracts import ContractContainer


def deploy_test_blueprint(project: Project, contract: Contract, account):
    initcode = contract.contract_type.deployment_bytecode.bytecode

    if isinstance(initcode, str):
        initcode = bytes.fromhex(initcode.removeprefix("0x"))

    initcode = b"\xfe\x71\x00" + initcode  # eip-5202 preamble version 0

    initcode = b"\x61" + len(initcode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + initcode

    tx = project.provider.network.ecosystem.create_transaction(
        chain_id=project.provider.chain_id,
        data=initcode,
        gas_price=project.provider.gas_price,
        nonce=account.nonce,
    )

    tx.gas_limit = project.provider.estimate_gas_cost(tx)
    tx = account.sign_transaction(tx)
    receipt = project.provider.send_transaction(tx)
    return receipt.contract_address


def mint_tokens_for_testing(project: Project, account, stablecoin_amount: int, eth_amount: int):
    """
    Provides given account with 1M of stablecoins - USDC, USDT, USDP and TUSD and with 1000 ETH and WETH
    Can be used only on local forked mainnet

    :return: None
    """

    # USDC
    token_contract = Contract("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    token_minter = "0xe982615d461dd5cd06575bbea87624fda4e3de17"
    project.provider.set_balance(token_minter, 10**18)
    amount = stablecoin_amount * 10**token_contract.decimals()
    token_contract.configureMinter(token_minter, amount, sender=token_minter)
    token_contract.mint(account, amount, sender=token_minter)
    assert token_contract.balanceOf(account.address) >= amount

    # USDT
    token_contract = Contract("0xdAC17F958D2ee523a2206206994597C13D831ec7")
    token_owner = "0xc6cde7c39eb2f0f0095f41570af89efc2c1ea828"
    project.provider.set_balance(token_owner, 10**18)
    amount = stablecoin_amount * 10**token_contract.decimals()
    token_contract.issue(amount, sender=token_owner)
    token_contract.transfer(account, amount, sender=token_owner)
    assert token_contract.balanceOf(account.address) >= amount

    # USDP
    token_contract = Contract("0x8E870D67F660D95d5be530380D0eC0bd388289E1")
    token_supply_controller = token_contract.supplyController()
    project.provider.set_balance(token_supply_controller, 10**18)
    amount = stablecoin_amount * 10**token_contract.decimals()
    token_contract.increaseSupply(amount, sender=token_supply_controller)
    token_contract.transfer(account, amount, sender=token_supply_controller)
    assert token_contract.balanceOf(account.address) >= amount

    # TUSD
    token_contract = Contract("0x0000000000085d4780B73119b644AE5ecd22b376")
    # apply proxy
    token_impl = ContractContainer(Contract(token_contract.implementation()).contract_type)
    token_contract = token_impl.at("0x0000000000085d4780B73119b644AE5ecd22b376")

    token_owner = token_contract.owner()
    project.provider.set_balance(token_owner, 10**18)
    amount = stablecoin_amount * 10**token_contract.decimals()
    token_contract.mint(account, amount, sender=token_owner)
    assert token_contract.balanceOf(account.address) >= amount

    # ETH
    # Set balance to twice amount + 1 - half will be wrapped + (potential) gas
    project.provider.set_balance(account.address, 2 * eth_amount * 10**18)
    assert account.balance >= 2 * eth_amount * 10**18

    # WETH
    weth_contract = Contract("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    weth_contract.deposit(value=eth_amount * 10**18, sender=account)
    assert weth_contract.balanceOf(account.address) >= eth_amount * 10**18
