from eth_abi import encode
import boa


def test_leverage(borrower, controller, leverage_zap, router, crvusd, weth):
    with boa.env.prank(borrower):
        # --- CREATE LOAN ---

        weth.approve(controller.address, 2**256 - 1)

        exchange_data = router.exchange.prepare_calldata(
            crvusd.address, weth.address, 10**21, 3 * 10**17
        )
        calldata = encode(["address", "bytes"], [router.address, exchange_data])

        with boa.reverts("Slippage"):
            controller.create_loan_extended(
                10**18, 10**21, 10, leverage_zap, [0, 9, 0, 3 * 10**17 + 1], calldata
            )
        controller.create_loan_extended(
            10**18, 10**21, 10, leverage_zap, [0, 9, 0, 3 * 10**17], calldata
        )

        state0 = controller.user_state(
            borrower
        )  # collateral: 1.3 ETH, debt: 1000 crvUSD
        assert state0[0] == 10**18 + 3 * 10**17
        assert state0[2] == 10**21

        # --- BORROW MORE ---

        with boa.reverts("Slippage"):
            controller.borrow_more_extended(
                10**17, 10**21, leverage_zap, [0, 9, 0, 3 * 10**17 + 1], calldata
            )
        controller.borrow_more_extended(
            10**17, 10**21, leverage_zap, [0, 9, 0, 3 * 10**17], calldata
        )

        state1 = controller.user_state(
            borrower
        )  # collateral: 1.7 ETH, debt: 2000 crvUSD
        assert state1[0] == state0[0] + 10**17 + 3 * 10**17
        assert state1[2] == state0[2] + 10**21

        # --- REPAY ---

        exchange_data = router.exchange.prepare_calldata(
            weth.address, crvusd.address, 10**18, 15 * 10**20
        )
        calldata = encode(["address", "bytes"], [router.address, exchange_data])

        with boa.reverts("Slippage"):
            controller.repay_extended(
                leverage_zap, [0, 9, 0, 0, 15 * 10**20 + 1], calldata
            )
        controller.repay_extended(leverage_zap, [0, 9, 0, 0, 15 * 10**20], calldata)

        state2 = controller.user_state(
            borrower
        )  # collateral: 0.7 ETH, debt: 500 crvUSD
        assert state2[0] == state1[0] - 10**18
        assert state2[2] == state1[2] - 15 * 10**20
