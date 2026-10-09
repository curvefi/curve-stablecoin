# pragma version 0.4.3
# pragma optimize codesize

"""
@title LlamaLend Intents — shared machinery (module)
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice EIP-712 domain/hashing/signature verification, nonce cancellation
        bitmap, cumulative partial-fill accounting, trigger conditions and
        Dutch fee decay. Stateful module: initialized once by the deployed
        executor; `executor_core` accesses it via `uses`.
@custom:security security@curve.finance
"""

from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IAMM


interface IERC1271:
    def isValidSignature(_hash: bytes32, _sig: Bytes[65]) -> bytes4: view


################################################################
#                          CONSTANTS                           #
################################################################

WAD: constant(uint256) = 10**18
BPS: constant(uint256) = 10**4
ERC1271_MAGIC: constant(bytes4) = 0x1626ba7e
# sentinel for "condition unset" on int256 fields
UNSET_INT: constant(int256) = max_value(int256)

NAME_HASH: constant(bytes32) = keccak256("LlamaLend Intents")
VERSION_HASH: constant(bytes32) = keccak256("1")
EIP712_DOMAIN_TYPEHASH: constant(bytes32) = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)

# NOTE: field names below are what wallets render — keep camelCase, keep order
#       identical to the Common struct.
COMMON_TYPE: constant(String[256]) = (
    "Common(address user,address controller,uint256 priceBelow,"
    "uint256 priceAbove,int256 healthBelow,uint256 rateAbove,"
    "uint256 rateBelow,uint256 deadline,uint256 nonce,uint256 minFill,"
    "uint256 cooldown,uint256 feeStartBps,uint256 feeEndBps,uint256 decayStart)"
)
COMMON_TYPEHASH: constant(bytes32) = keccak256(COMMON_TYPE)


################################################################
#                           STRUCTS                            #
################################################################

struct Common:
    user: address
    controller: address
    # trigger conditions; 0 = unset for uints, UNSET_INT for healthBelow
    price_below: uint256    # fill only while oracle price <= this
    price_above: uint256    # fill only while oracle price >= this
    health_below: int256    # fill only while health(user) < this (auto-delever)
    rate_above: uint256     # fill only while AMM.rate() >= this
    rate_below: uint256     # fill only while AMM.rate() <= this
    # validity / replay / partial fills
    deadline: uint256       # end of the whole fill window
    nonce: uint256          # Permit2-style unordered nonce (cancellation only;
                            # fills are bounded by the cumulative cap instead)
    min_fill: uint256       # min slice per fill, in intent units (anti-dust)
    cooldown: uint256       # min seconds between partial fills
    # Dutch fee decay: bps grows fee_start -> fee_end over [decay_start, deadline]
    fee_start_bps: uint256
    fee_end_bps: uint256
    decay_start: uint256


################################################################
#                            STATE                             #
################################################################

# intent digest => cumulative filled amount (intent units)
filled: public(HashMap[bytes32, uint256])
# intent digest => last fill timestamp (cooldown)
last_fill: public(HashMap[bytes32, uint256])
# user => word => bitmap of cancelled nonces
nonce_bitmap: public(HashMap[address, HashMap[uint256, uint256]])


event Cancel:
    user: indexed(address)
    word: uint256
    mask: uint256


################################################################
#                       EIP-712 & SIGNATURES                   #
################################################################

@internal
@view
def _domain_separator() -> bytes32:
    return keccak256(
        abi_encode(EIP712_DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, chain.id, self)
    )


@internal
@view
def _digest(_struct_hash: bytes32) -> bytes32:
    return keccak256(concat(b"\x19\x01", self._domain_separator(), _struct_hash))


@internal
@view
def _hash_common(c: Common) -> bytes32:
    return keccak256(
        abi_encode(
            COMMON_TYPEHASH,
            c.user,
            c.controller,
            c.price_below,
            c.price_above,
            c.health_below,
            c.rate_above,
            c.rate_below,
            c.deadline,
            c.nonce,
            c.min_fill,
            c.cooldown,
            c.fee_start_bps,
            c.fee_end_bps,
            c.decay_start,
        )
    )


@internal
@view
def _verify_sig(_user: address, _digest_: bytes32, _sig: Bytes[65]):
    """ECDSA for EOAs, ERC-1271 for smart accounts."""
    assert _user != empty(address), "user=0"
    if _user.is_contract:
        assert (
            staticcall IERC1271(_user).isValidSignature(_digest_, _sig) == ERC1271_MAGIC
        ), "bad 1271 sig"
    else:
        assert len(_sig) == 65, "bad sig len"
        r: bytes32 = extract32(_sig, 0)
        s: bytes32 = extract32(_sig, 32)
        v: uint256 = convert(slice(_sig, 64, 1), uint256)
        if v < 27:
            v += 27
        assert ecrecover(_digest_, v, r, s) == _user, "bad sig"


################################################################
#                    CONDITIONS / VALIDITY                     #
################################################################

@internal
@view
def _check_valid(c: Common, _h: bytes32):
    assert block.timestamp <= c.deadline, "expired"
    assert (
        self.nonce_bitmap[c.user][c.nonce >> 8] & (1 << (c.nonce & 255)) == 0
    ), "cancelled"
    assert block.timestamp >= self.last_fill[_h] + c.cooldown, "cooldown"
    assert c.fee_end_bps >= c.fee_start_bps and c.fee_end_bps < BPS, "bad fee"


@internal
@view
def _check_conditions(c: Common):
    ctrl: IController = IController(c.controller)
    amm: IAMM = staticcall ctrl.amm()
    if c.price_below != 0 or c.price_above != 0:
        p: uint256 = staticcall amm.price_oracle()
        if c.price_below != 0:
            assert p <= c.price_below, "price>bound"
        if c.price_above != 0:
            assert p >= c.price_above, "price<bound"
    if c.health_below != UNSET_INT:
        assert staticcall ctrl.health(c.user, False) < c.health_below, "healthy"
    if c.rate_above != 0 or c.rate_below != 0:
        r: uint256 = staticcall amm.rate()
        if c.rate_above != 0:
            assert r >= c.rate_above, "rate<bound"
        if c.rate_below != 0:
            assert r <= c.rate_below, "rate>bound"


################################################################
#                       FILL ACCOUNTING                        #
################################################################

@internal
@view
def _remaining(_h: bytes32, _cap: uint256) -> uint256:
    return _cap - self.filled[_h]


@internal
def _register_fill(_h: bytes32, c: Common, _cap: uint256, _d: uint256):
    """
    Record a fill of `_d` intent units against cumulative cap `_cap`.
    A slice smaller than min_fill is only allowed when it finishes the intent.
    """
    f: uint256 = self.filled[_h]
    assert _d > 0, "zero fill"
    assert f + _d <= _cap, "cap"
    assert _d >= c.min_fill or f + _d == _cap, "dust"
    self.filled[_h] = f + _d
    self.last_fill[_h] = block.timestamp


################################################################
#                        DUTCH FEE DECAY                       #
################################################################

@internal
@view
def _fee_bps(c: Common) -> uint256:
    if block.timestamp <= c.decay_start or c.deadline <= c.decay_start:
        return c.fee_start_bps
    if block.timestamp >= c.deadline:
        return c.fee_end_bps
    return c.fee_start_bps + (c.fee_end_bps - c.fee_start_bps) * (
        block.timestamp - c.decay_start
    ) // (c.deadline - c.decay_start)


################################################################
#                         CANCELLATION                         #
################################################################

@internal
def _cancel(_user: address, _word: uint256, _mask: uint256):
    self.nonce_bitmap[_user][_word] |= _mask
    log Cancel(user=_user, word=_word, mask=_mask)
