# Lending and borrowing using LLAMMa

## High-level overview

Curve stablecoin crvUSD uses LLAMMa for soft liquidations (code in AMM.vy). However, this AMM allows to be used for any
pair of tokens.

This code creates lending/borrowing markets to borrow crvUSD against any tokens, or to borrow any tokens against crvUSD
in isolated mode. At first, we create "simple" non-rehypothecating markets, and later - cross-markets where collateral
provided is lent out to be used as borrow liquidity while making some APR on that.

Liquidity gets provided in Vaults which are ERC4626 contracts (however with some additional methods for convenience).

## Smart contracts and their differences from original Curve stablecoin contracts

### AMM.vy

The core contract `AMM.vy` stays exactly the same. It is already exactly like we need for lending, no changes needed.

### Controller.vy

The Controller has an ability to not only 18-digit tokens (like crvUSD) but tokens with any number of digits. For that,
there were multiple changes to make sure rounding aways rounds up in favor of the exisitng borrowers.

Method which collects borrowing fees `collect_fees()` will not work in lending. Admin fees are zero, and all the
interest will go to the vault depositors. Moreover, AMM admin fees cannot be charged: their claim would fail to.
This is intentional: system will make money on fees made by crvUSD itself.

The contract which creates the Controller can have `collateral_token()` and `borrowed_token()` public methods instead of
a `stablecoin()` method. This is to keep the code clean and understandable when stablecoin is collateral, not borrowed.
However, compatibility with `stablecoin()` method is preserved.

Transfer of native ETH are removed for safety. Multiple hacks in DeFi were due to integrators mishandling ETH transfers,
and also due to error. To keep things safer with unknown unknowns, automatic wrapping of ETH is turned off for good.

Both `Controller.vy` and `AMM.vy` can be used for the stablecoin in this same form, to keep codebase the same.

### Vault.vy

The vault is an implementation of ERC4626 vault which deposits into controller and tracks the progress of the fees earned. Vault is a standard facrory (non-blueprint) contract which also creates AMM and Controller using `initialize()`.

Unlike standard ERC4626 methods, it also has `borrow_apr()`, `lend_apr()`, `pricePerShare()`. Also, optionally, methods
`mint()`, `deposit()`, `redeem()`, `withdraw()` can have receiver not specified - in such case `msg.sender` is the
receiver.

### OneWayLendingFactory.vy

Factory of borrowing/lending markets (with NO rehypothecation). Notable feature is that it can create markets from pools
which have `price_oracle()` method - in that case a special price oracle is not needed. However, pools must be
stableswap-ng, tricrypto-ng or twocrypto-ng.

### CryptoFromPool.vy

Price oracle contract to use `price_oracle()` method of a pool, used by `from_pool()` creation method.

### SemilogMonetaryPolicy.vy

This is monetary policy for lending markets where borrow rate does not depend on crvUSD peg but just on utilization of
the market. The function is as simple as:

```
    log(rate) = utilization * (log(rate_max) - log(rate_min)) + log(rate_min)
        e.g.
    rate = rate_min * (rate_max / rate_min)**utilization
```
