Stablecoin Contract
===================

.. module:: stablecoin

Functions
---------

.. function:: transferFrom(_from: address, _to: address, _value: uint256) -> bool

    Transfer funds between two accounts using a previously granted approval from the
    originating account to the caller.

    :param address _from: The account funds will originate from.
    :param address _to: The account to credit funds to.
    :param uint256 _value: The amount of funds to transfer.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient allowance granted by the originating account.
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the originating account has an insufficient balance.

.. function:: transfer(_to: address, _value: uint256) -> bool

    Transfer funds from the caller to another account.

    :param address _to: The account to credit funds to.
    :param uint256 _value: The amount of funds to transfer.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the caller has an insufficient balance.

.. function:: approve(_spender: address, _value: uint256) -> bool

    Allow an account to transfer up to ``_value`` amount of the caller's funds.

    :param address _spender: The account to grant an allowance to.
    :param uint256 _value: The total allowance amount.
    :returns: ``True`` iff the function is successful.
    :rtype: bool

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
