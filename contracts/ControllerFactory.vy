# @version 0.3.1

interface ERC20:
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable

interface Controller:
    def initialize(
        collateral_token: address, monetary_policy: address,
        loan_discount: uint256, liquidation_discount: uint256,
        amm: address, debt_ceiling: uint256
    ): nonpayable

interface AMM:
    def initialize(
        _A: uint256, _base_price: uint256, _collateral_token: address, fee: uint256, admin_fee: uint256,
        _price_oracle_contract:address, _price_oracle_sig: bytes32,
    ): nonpayable


interface Stablecoin:
    def set_minter(_minter: address, _enabled: bool): nonpayable


event AddMarket:
    collateral: address
    controller: address
    amm: address
    monetary_policy: address


STABLECOIN: immutable(address)
controllers: public(HashMap[address, address])
amms: public(HashMap[address, address])
admin: public(address)
fee_receiver: public(address)
controller_implementation: public(address)
amm_implementation: public(address)


@external
def __init__(stablecoin: address,
             admin: address,
             fee_receiver: address):
    STABLECOIN = stablecoin
    self.admin = admin
    self.fee_receiver = fee_receiver


@external
@view
def stablecoin() -> address:
    return STABLECOIN


@external
def add_market(token: address, A: uint256, fee: uint256, admin_fee: uint256,
                  _price_oracle_contract: address, _price_oracle_sig: bytes32,
                  monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
                  debt_ceiling: uint256) -> address[2]:
    assert msg.sender == self.admin, "Only admin"
    assert self.controllers[token] == ZERO_ADDRESS and self.amms[token] == ZERO_ADDRESS, "Already exists"


    response: Bytes[32] = raw_call(
        _price_oracle_contract,
        slice(_price_oracle_sig, 28, 4),
        is_static_call=True,
        max_outsize=32
    )
    p: uint256 = convert(response, uint256)

    amm: address = create_forwarder_to(self.amm_implementation)
    controller: address = create_forwarder_to(self.controller_implementation)
    AMM(amm).initialize(A, p, token, fee, admin_fee, _price_oracle_contract, _price_oracle_sig)
    Controller(controller).initialize(token, monetary_policy, loan_discount, liquidation_discount, amm, debt_ceiling)
    Stablecoin(STABLECOIN).set_minter(controller, True)
    log AddMarket(token, controller, amm, monetary_policy)
    return [controller, amm]


@external
def set_implementations(controller: address, amm: address):
    assert msg.sender == self.admin
    self.controller_implementation = controller
    self.amm_implementation = amm


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
def set_fee_receiver(fee_receiver: address):
    assert msg.sender == self.admin
    self.fee_receiver = fee_receiver
