Stablecoin Contract
===================

.. module:: stablecoin

Functions
---------

.. function:: transferFrom(_from: address, _to: address, _value: uint256) -> bool

    Transfer tokens between two accounts using a previously granted approval from the
    originating account to the caller.

    :param address _from: The account tokens will originate from.
    :param address _to: The account to credit tokens to.
    :param uint256 _value: The amount of tokens to transfer.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient allowance granted by the originating account.
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the originating account has an insufficient balance.
    :log: :class:`Approval` - iff the caller's allowance is less than ``MAX_UINT256``.
    :log: :class:`Transfer`

.. function:: transfer(_to: address, _value: uint256) -> bool

    Transfer tokens from the caller to another account.

    :param address _to: The account to credit tokens to.
    :param uint256 _value: The amount of tokens to transfer.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the caller has an insufficient balance.
    :log: :class:`Transfer`

.. function:: approve(_spender: address, _value: uint256) -> bool

    Allow an account to transfer up to ``_value`` amount of the caller's tokens.

    .. note::

        This function is suceptible to front running as described `here <https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729>`_.
        Use the :func:`increaseAllowance` and :func:`decreaseAllowance` functions to mitigate the described race condition.

    :param address _spender: The account to grant an allowance to.
    :param uint256 _value: The total allowance amount.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :log: :class:`Approval`

.. function:: permit(_owner: address, _spender: address, _value: uint256, _deadline: uint256, _v: uint8, _r: bytes32, _s: bytes32) -> bool

    Allow an account to transfer up to ``_value`` amount of ``_owner``'s tokens via a signature.

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

    Burn tokens from an account using a previously granted allowance.

    :param address _from: The account to burn tokens from.
    :param uint256 _value: The amount of tokens to burn.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient allowance.
    :reverts: If the account tokens are to be burned from has an insufficient balance.
    :log: :class:`Approval` - iff the caller's allowance is less than ``MAX_UINT256``.
    :log: :class:`Transfer`

.. function:: burn(_value: uint256) -> bool

    Burn tokens.

    :param uint256 _value: The amount of tokens to burn.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller has an insufficient balance.
    :log: :class:`Transfer`

.. function:: mint(_to: address, _value: uint256) -> bool

    Mint new tokens to ``_to``.

    :param address _to: The account to received the newly minted tokens.
    :param uint256 _value: The amount of tokens to mint.
    :returns: ``True`` iff the function is successful.
    :rtype: bool
    :reverts: If the caller is not the :func:`minter`.
    :reverts: If the receiving account is either the zero address, or the token contract itself.
    :reverts: If the :func:`balanceOf` the receiver overflows.
    :reverts: If :func:`totalSupply` overflows.
    :log: :class:`Transfer`

.. function:: add_minter(_minter: address)

    Grant an account the ability to mint tokens.

    :param address _minter: The account to grant permissions to.
    :reverts: If the caller is not the :func:`admin`

.. function:: remove_minter(_minter: address)

    Revoke an account's ability to mint tokens.

    :param address _minter: The account to revoke the permissions of.
    :reverts: If the caller is not the :func:`admin`

.. function:: set_admin(_new_admin: address)

    Set the admin, which is capable of calling :func:`mint`, :func:`add_minter` and :func:`remove_minter`.

    :param address _new_admin: The account to set as the new admin.
    :reverts: If the caller is not the current :func:`admin`.
    :log: :class:`SetAdmin`

Read-Only Functions
-------------------

.. function:: DOMAIN_SEPARATOR() -> bytes32

    Get the :eip:`712` domain separator for this contract.

    **In the event of a chain fork, this value is updated to prevent replay attacks.**

    :rtype: bytes32

.. function:: is_minter(_account: address) -> bool

    Query whether an account is allowed to call the :func:`mint` function.

    :param address _account: The account to query the privilege of.
    :returns: Whether an account is allowed to call :func:`mint`.
    :rtype: bool

.. function:: name() -> String[64]

    Get the token contract's full name.

    :rtype: String[64]

.. function:: symbol() -> String[32]

    Get the token contract's currency symbol.

    :rtype: String[32]

.. function:: salt() -> bytes32

    Get the salt value used for calculating the :func:`DOMAIN_SEPARATOR`.

    :rtype: bytes32

.. function:: allowance(_owner: address, _spender: address) -> uint256

    Get the allowance granted to ``_spender`` from ``_owner``.

    :param address _owner: The account tokens will originate from.
    :param address _spender: The account allowed to spend ``_owner``'s tokens.
    :rtype: uint256

.. function:: balanceOf(_owner: address) -> uint256

    Get the token balance of an account.

    :param address _owner: The account to query the balance of.
    :rtype: uint256

.. function:: totalSupply() -> uint256

    Get the total tokens in circulation.

    :rtype: uint256

.. function:: nonces(_owner: address) -> uint256

    Get the :eip:`2612` permit signature nonce of an account.

    :param address _owner: The account to query the nonce of.
    :rtype: uint256

.. function:: admin() -> address

    Get the account with administrator privileges.

    :rtype: address

Events
------

.. class:: Approval(owner: address, spender: address, value: uint256)

    See :eip:`20`.

.. class:: Transfer(sender: address, receiver: address, value: uint256)

    See :eip:`20`.

.. class:: SetAdmin(admin: address)

    Logged when the contract's :func:`admin` changes.

.. class:: AddMinter(minter: address)

    Logged when an account is granted the minter role.

.. class:: RemoveMinter(minter: address)

    Logged when an account has it's minter role revoked.
