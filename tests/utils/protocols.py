"""
Deploy function for the complete llamalend protocol suite.
Provides deployment of both mint and lending markets with all necessary contracts.
"""

import boa
from boa.contracts.vyper.vyper_contract import (
    VyperDeployer,
    VyperBlueprint,
    VyperContract,
)
from typing import Dict, Any

from tests.utils.constants import MAX_UINT256


from tests.utils.deployers import (
    # Core contracts
    STABLECOIN_DEPLOYER,
    AMM_DEPLOYER,
    CONTROLLER_FACTORY_DEPLOYER,
    CONTROLLER_VIEW_DEPLOYER,
    # Lending contracts
    VAULT_DEPLOYER,
    LEND_CONTROLLER_DEPLOYER,
    LEND_CONTROLLER_VIEW_DEPLOYER,
    LENDING_FACTORY_DEPLOYER,
    # Price oracles
    DUMMY_PRICE_ORACLE_DEPLOYER,
    CRYPTO_FROM_POOL_DEPLOYER,
    # Monetary policies
    CONSTANT_MONETARY_POLICY_DEPLOYER,
    CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
    SEMILOG_MONETARY_POLICY_DEPLOYER,
    WETH_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
    # Compiler flags
    compiler_args_codesize,
)


class Blueprints:
    def __init__(self, **deployers: VyperDeployer):
        for name, deployer in deployers.items():
            setattr(self, name, deployer.deploy_as_blueprint())

    amm: VyperBlueprint
    mint_controller: VyperBlueprint
    lend_controller: VyperBlueprint
    lend_controller_view: VyperBlueprint
    price_oracle: VyperBlueprint
    mpolicy: VyperBlueprint
    vault: VyperBlueprint


class Llamalend:
    """
    Protocol deployment and management class for llamalend.
    Handles deployment of core infrastructure and creation of markets.
    """

    def __init__(self, initial_price: int = 3000 * 10**18):
        """
        Deploy the complete llamalend protocol suite.

        Args:
            admin: Admin address for all contracts
            initial_price: Initial price for oracles (e.g., 3000 * 10**18)
        """
        self.admin = boa.env.generate_address("admin")
        self.fee_receiver = boa.env.generate_address("fee_receiver")

        controller_view_blueprint = CONTROLLER_VIEW_DEPLOYER.deploy_as_blueprint()

        with open("contracts/MintController.vy", "r") as f:
            mint_controller_code = f.read()
        mint_controller_code = mint_controller_code.replace(
            "empty(address),  # to replace at deployment with view blueprint",
            f"{controller_view_blueprint.address},",
            1,
        )
        assert f"{controller_view_blueprint.address}," in mint_controller_code

        # This is a bit of a special case that breaks our current conventions around
        # deployers. The only reason why this was done is because since we can't change
        # the constructor arguments of the MintController contract, we have to
        # manually patch the code to insert the correct address of the controller view
        # which is only known at runtime.
        self._mint_controller_deployer = boa.loads_partial(
            mint_controller_code, compiler_args=compiler_args_codesize
        )

        # Deploy all blueprints
        self.blueprints = Blueprints(
            amm=AMM_DEPLOYER,
            mint_controller=self._mint_controller_deployer,
            lend_controller=LEND_CONTROLLER_DEPLOYER,
            lend_controller_view=LEND_CONTROLLER_VIEW_DEPLOYER,
            price_oracle=CRYPTO_FROM_POOL_DEPLOYER,
            mpolicy=CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
            vault=VAULT_DEPLOYER,
        )

        # Deploy core infrastructure
        with boa.env.prank(self.admin):
            # Deploy stablecoin
            self.crvUSD = STABLECOIN_DEPLOYER.deploy("Curve USD", "crvUSD")
            self.__init_mint_markets(initial_price)
            self.__init_lend_markets()

    def __init_mint_markets(self, initial_price):
        # Deploy WETH
        self.weth = WETH_DEPLOYER.deploy()

        # Deploy a dummy price oracle for testing
        self.price_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(
            self.admin, initial_price
        )

        # Deploy Mint Protocol
        # Deploy controller factory
        self.mint_factory = CONTROLLER_FACTORY_DEPLOYER.deploy(
            self.crvUSD.address, self.admin, self.fee_receiver, self.weth.address
        )

        # Set implementations on factory using blueprints
        self.mint_factory.set_implementations(
            self.blueprints.mint_controller.address, self.blueprints.amm.address
        )

        # Set stablecoin minter to factory
        self.crvUSD.set_minter(self.mint_factory.address)

        # Deploy monetary policy for mint markets
        self.mint_monetary_policy = CONSTANT_MONETARY_POLICY_DEPLOYER.deploy(self.admin)

    def __init_lend_markets(self):
        # Deploy Lending Protocol
        # Deploy lending factory
        self.lending_factory = LENDING_FACTORY_DEPLOYER.deploy(
            self.blueprints.amm.address,
            self.blueprints.lend_controller.address,
            self.blueprints.vault.address,
            self.blueprints.price_oracle.address,
            self.blueprints.lend_controller_view.address,
            self.admin,
            self.fee_receiver,
        )

    def create_mint_market(
        self,
        collateral_token: VyperContract,
        price_oracle: VyperContract,
        monetary_policy: VyperContract,
        A: int,
        amm_fee: int,
        loan_discount: int,
        liquidation_discount: int,
        debt_ceiling: int,
    ) -> Dict[str, VyperContract]:
        """
        Create a new mint market in the Controller Factory.

        Args:
            collateral_token: Collateral token contract
            price_oracle: Price oracle contract
            monetary_policy: Monetary policy contract for this market
            A: AMM amplification parameter (e.g., 100)
            fee: Trading fee (e.g., 10**16 for 1%)
            loan_discount: Loan discount (e.g., 9 * 10**16 for 9%)
            liquidation_discount: Liquidation discount (e.g., 6 * 10**16 for 6%)
            debt_ceiling: Maximum debt for this market (e.g., 10**6 * 10**18)

        Returns:
            Dictionary with 'controller' and 'amm' contracts
        """
        self.mint_factory.add_market(
            collateral_token.address,
            A,
            amm_fee,
            0,  # admin fee deprecated for mint markets
            price_oracle.address,
            monetary_policy.address,
            loan_discount,
            liquidation_discount,
            debt_ceiling,
            sender=self.admin,
        )

        controller_address = self.mint_factory.get_controller(collateral_token.address)
        amm_address = self.mint_factory.get_amm(collateral_token.address)

        return {
            "controller": self._mint_controller_deployer.at(controller_address),
            "amm": AMM_DEPLOYER.at(amm_address),
        }

    def create_lending_market(
        self,
        borrowed_token: VyperContract,
        collateral_token: Any,
        A: int,
        fee: int,
        loan_discount: int,
        liquidation_discount: int,
        price_oracle: VyperContract,
        name: str,
        min_borrow_rate: int,
        max_borrow_rate: int,
        seed_amount: int = 1000 * 10**18,
        mpolicy_deployer: VyperDeployer | None = None,
        supply_limit: int = MAX_UINT256,
    ) -> Dict[str, VyperContract]:
        """
        Create a new lending market in the Lending Factory.

        Args:
            borrowed_token: Token to be borrowed
            collateral_token: Token used as collateral
            A: AMM amplification parameter (e.g., 100)
            fee: Trading fee (e.g., 6 * 10**15 for 0.6%)
            loan_discount: Loan discount (e.g., 9 * 10**16 for 9%)
            liquidation_discount: Liquidation discount (e.g., 6 * 10**16 for 6%)
            price_oracle: Price oracle contract
            name: Name for the vault
            min_borrow_rate: Minimum borrow rate (e.g., 0.5 * 10**16 for 0.5%)
            max_borrow_rate: Maximum borrow rate (e.g., 50 * 10**16 for 50%)
            seed_amount: Borrowed token amount to seed into the vault post-deployment
            mpolicy_deployer: Optional monetary policy deployer override
            supply_limit: Vault supply cap passed to the factory (defaults to MAX_UINT256 for no cap)

        Returns:
            Dictionary with 'vault', 'controller', 'amm' contracts.
        """
        policy_deployer = mpolicy_deployer or CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER

        deploy_args = [
            borrowed_token.address,
            min_borrow_rate,
            max_borrow_rate,
        ]
        if policy_deployer is SEMILOG_MONETARY_POLICY_DEPLOYER:
            deploy_args.append(self.lending_factory.address)

        monetary_policy = policy_deployer.deploy(*deploy_args)

        result = self.lending_factory.create(
            borrowed_token.address,
            collateral_token.address,
            A,
            fee,
            loan_discount,
            liquidation_discount,
            price_oracle.address,
            monetary_policy.address,
            name,
            supply_limit,
            sender=self.admin,
        )

        vault = VAULT_DEPLOYER.at(result[0])
        controller = LEND_CONTROLLER_DEPLOYER.at(result[1])
        amm = AMM_DEPLOYER.at(result[2])

        # Seed lending markets by depositing borrowed token into the vault
        if seed_amount and seed_amount > 0:
            with boa.env.prank(self.admin):
                boa.deal(borrowed_token, self.admin, seed_amount)
                borrowed_token.approve(vault.address, 2**256 - 1)
                vault.deposit(seed_amount)

        return {
            "vault": vault,
            "controller": controller,
            "amm": amm,
        }


if __name__ == "__main__":
    proto = Protocol()

    # Test mint market creation
    collat = ERC20_MOCK_DEPLOYER.deploy(18)
    mint_market = proto.create_mint_market(
        collat,
        proto.price_oracle,
        proto.mint_monetary_policy,
        A=100,
        amm_fee=10**16,
        loan_discount=9 * 10**16,  # 9%
        liquidation_discount=6 * 10**16,  # 6%
        debt_ceiling=10**6 * 10**18,
    )

    # Test lending market creation
    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(18)
    collat_token = ERC20_MOCK_DEPLOYER.deploy(18)

    lending_market = proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collat_token,
        A=100,
        fee=6 * 10**15,  # 0.6%
        loan_discount=9 * 10**16,  # 9%
        liquidation_discount=6 * 10**16,  # 6%
        price_oracle=proto.price_oracle,
        name="Test Vault",
        min_borrow_rate=5 * 10**15 // (365 * 86400),  # 0.5% APR
        max_borrow_rate=50 * 10**16 // (365 * 86400),  # 50% APR
    )
