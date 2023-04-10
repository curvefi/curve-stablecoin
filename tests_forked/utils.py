def deploy_test_blueprint(project, contract, account):
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
