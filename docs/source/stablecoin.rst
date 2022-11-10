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
    :log: :class:`Approval` - iff the caller's allowance is less than ``MAX_UINT256``.
    :log: :class:`Transfer`

.. function:: transfer(_to: address, _value: uint256) -> bool

    Transfer funds from the caller to another account.

    :param address _to: The account to credit funds to.
    :param uint256 _value: The amount of funds to transfer.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the caller has an insufficient balance.
    :log: :class:`Transfer`

.. function:: approve(_spender: address, _value: uint256) -> bool

    Allow an account to transfer up to ``_value`` amount of the caller's funds.

    .. note::

        This function is suceptible to front running as described `here <https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729>`_.
        Use the :func:`increaseAllowance` and :func:`decreaseAllowance` functions to mitigate the described race condition.

    :param address _spender: The account to grant an allowance to.
    :param uint256 _value: The total allowance amount.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :log: :class:`Approval`

.. function:: permit(_owner: address, _spender: address, _value: uint256, _deadline: uint256, _v: uint8, _r: bytes32, _s: bytes32) -> bool

    Allow an account to transfer up to ``_value`` amount of ``_owner``'s funds via a signature.

    :param address _owner: The account granting an approval and which generated the signature provided.
    :param address _spender: The account the allowance is granted to.
    :param uint256 _value: The total allowance amount.
    :param uint256 _deadline: The timestamp after which the signature is considered invalid.
    :param uint8 _v: The last byte of the generated signature. 
    :param bytes32 _r: The first 32 byte chunk of the generated signature.
    :param bytes32 _s: The second 32 byte chunk of the generated signature.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the ``_owner`` argument is the zero address.
    :reverts: If the ``block.timestamp`` at execution is greater than the ``deadline`` argument.
    :reverts: If the recovered signer is not equivalent to the ``_owner`` argument.
    :log: :class:`Approval`

.. function:: increaseAllowance(_spender: address, _add_value: uint256) -> bool

    Increase the allowance granted to ``_spender`` by the caller.

    **If an overflow were to occur, the allowance is instead set to** ``MAX_UINT256``.

    :param address _spender: The account to increase the allowance of.
    :param uint256 _add_value: The amount to increase the allowance by.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :log: :class:`Approval` - iff the allowance is updated to a new value.

.. function:: decreaseAllowance(_spender: address, _sub_value: uint256) -> bool

    Decrease the allowance granted to ``_spender`` by the caller.

    **If an underflow were to occur, the allowance is instead set to** ``0``.

    :param address _spender: The account to decrease the allowance of.
    :param uint256 _sub_value: The amount to decrease the allowance by.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :log: :class:`Approval` - iff the allowance is updated to a new value.

.. function:: burnFrom(_from: address, _value: uint256) -> bool

    Burn funds from an account using a previously granted allowance.

    :param address _from: The account to burn funds from.
    :param uint256 _value: The amount of funds to burn.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient allowance.
    :reverts: If the account funds are to be burned from has an insufficient balance.
    :log: :class:`Approval` - iff the caller's allowance is less than ``MAX_UINT256``.
    :log: :class:`Transfer`

.. function:: burn(_value: uint256) -> bool

    Burn funds.

    :param uint256 _value: The amount of funds to burn.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient balance.
    :log: :class:`Transfer`

.. function:: mint(_to: address, _value: uint256) -> bool

    Mint new funds to ``_to``.

    :param address _to: The account to received the newly minted funds.
    :param uint256 _value: The amount of funds to mint.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller is not the :func:`minter`.
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the :func:`balanceOf` the receiver overflows.
    :reverts: If :func:`totalSupply` overflows.
    :log: :class:`Transfer`

.. function:: set_minter(_new_minter: address)

    Set the minter, which is capable of calling :func:`mint`.

    :param address _new_minter: The account to set as the new minter.
    :reverts: If the caller is not the current :func:`minter`.
    :log: :class:`SetMinter`

Read-Only Functions
-------------------

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
