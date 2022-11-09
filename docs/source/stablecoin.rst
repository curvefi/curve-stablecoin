Stablecoin Contract
===================

.. module:: stablecoin

Functions
---------

.. function:: transferFrom(_from: address, _to: address, _value: uint256) -> bool

.. function:: transfer(_to: address, _value: uint256) -> bool

.. function:: approve(_spender: address, _value: uint256) -> bool

.. function:: permit(_owner: address, _spender: address, _value: uint256, _deadline: uint256, _v: uint8, _r: bytes32, _s: bytes32) -> bool

.. function:: increaseAllowance(_spender: address, _add_value: uint256) -> bool

.. function:: decreaseAllowance(_spender: address, _sub_value: uint256) -> bool

.. function:: burnFrom(_from: address, _value: uint256) -> bool

.. function:: burn(_value: uint256) -> bool

.. function:: mint(_to: address, _value: uint256) -> bool

.. function:: set_minter(_new_minter: address)

View Functions
--------------

.. function:: DOMAIN_SEPARATOR() -> bytes32

.. function:: name() -> String[64]

.. function:: symbol() -> String[32]

.. function:: salt() -> bytes32

.. function:: allowance(_owner: address, _spender: address) -> uint256

.. function:: balanceOf(_owner: address) -> uint256

.. function:: totalSupply() -> uint256

.. function:: nonces(_owner: address) -> uint256

.. function:: minter() -> address

Events
------

.. class:: Approval(owner: address, spender: address, value: uint256)

.. class:: Transfer(sender: address, receiver: address, value: uint256)

.. class:: SetMinter(minter: address)
