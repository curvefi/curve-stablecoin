"""
Deploy function for the complete llamalend protocol suite.
Provides deployment of both mint and lending protocols with all necessary contracts.
"""

import boa
from typing import Dict, Any
from tests.utils.deployers import (
    # Core contracts
    STABLECOIN_DEPLOYER,
    AMM_DEPLOYER,
    MINT_CONTROLLER_DEPLOYER,
    CONTROLLER_FACTORY_DEPLOYER,
    
    # Lending contracts
    VAULT_DEPLOYER,
    LL_CONTROLLER_DEPLOYER,
    LENDING_FACTORY_DEPLOYER,
    
    # Price oracles
    DUMMY_PRICE_ORACLE_DEPLOYER,
    CRYPTO_FROM_POOL_DEPLOYER,
    
    # Monetary policies
    CONSTANT_MONETARY_POLICY_DEPLOYER,
    SEMILOG_MONETARY_POLICY_DEPLOYER,
    
    # Testing contracts
    WETH_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
)


class Protocol:
    """
    Protocol deployment and management class for llamalend.
    Handles deployment of core infrastructure and creation of markets.
    """
    
    def __init__(
        self,
        initial_price: int = 3000 * 10**18
    ):
        """
        Deploy the complete llamalend protocol suite.
        
        Args:
            admin: Admin address for all contracts
            initial_price: Initial price for oracles (e.g., 3000 * 10**18)
        """
        self.admin = boa.env.generate_address("admin")
        self.fee_receiver = boa.env.generate_address("fee_receiver")

        # Deploy core infrastructure
        with boa.env.prank(self.admin):
            # Deploy stablecoin
            self.crvUSD = STABLECOIN_DEPLOYER.deploy('Curve USD', 'crvUSD')
            
            # Deploy WETH
            self.weth = WETH_DEPLOYER.deploy()
            
            # Deploy shared AMM implementation (used by both mint and lending)
            self.amm_impl = AMM_DEPLOYER.deploy_as_blueprint()
            
            # Deploy a dummy price oracle for testing
            self.price_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(self.admin, initial_price)
            
            # Deploy Mint Protocol
            # Deploy controller implementation
            self.mint_controller_impl = MINT_CONTROLLER_DEPLOYER.deploy_as_blueprint()
            
            # Deploy controller factory
            self.mint_factory = CONTROLLER_FACTORY_DEPLOYER.deploy(
                self.crvUSD.address,
                self.admin,
                self.fee_receiver,
                self.weth.address
            )
            
            # Set implementations on factory
            self.mint_factory.set_implementations(
                self.mint_controller_impl.address,
                self.amm_impl.address
            )
            
            # Set stablecoin minter to factory
            self.crvUSD.set_minter(self.mint_factory.address)
            
            # Deploy monetary policy for mint markets
            self.mint_monetary_policy = CONSTANT_MONETARY_POLICY_DEPLOYER.deploy(self.admin)
            self.mint_monetary_policy.set_rate(0)  # 0% by default
            
            # Deploy Lending Protocol
            # Deploy vault implementation
            self.vault_impl = VAULT_DEPLOYER.deploy()
            
            # Deploy lending controller implementation
            self.ll_controller_impl = LL_CONTROLLER_DEPLOYER.deploy_as_blueprint()
            
            # Deploy price oracle implementation for lending
            self.price_oracle_impl = CRYPTO_FROM_POOL_DEPLOYER.deploy_as_blueprint()
            
            # Deploy monetary policy implementation for lending
            self.mpolicy_impl = SEMILOG_MONETARY_POLICY_DEPLOYER.deploy_as_blueprint()
            
            # Deploy lending factory
            self.lending_factory = LENDING_FACTORY_DEPLOYER.deploy(
                self.amm_impl.address,
                self.ll_controller_impl.address,
                self.vault_impl.address,
                self.price_oracle_impl.address,
                self.mpolicy_impl.address,
                self.admin,
                self.fee_receiver
            )
    
    def create_mint_market(
        self,
        collateral_token: Any,
        price_oracle: Any,
        monetary_policy: Any,
        A: int,
        amm_fee: int,
        admin_fee: int,
        loan_discount: int,
        liquidation_discount: int,
        debt_ceiling: int
    ) -> Dict[str, Any]:
        """
        Create a new mint market in the Controller Factory.
        
        Args:
            collateral_token: Collateral token contract
            price_oracle: Price oracle contract
            monetary_policy: Monetary policy contract for this market
            A: AMM amplification parameter (e.g., 100)
            fee: Trading fee (e.g., 10**16 for 1%)
            admin_fee: Admin fee share (e.g., 0)
            loan_discount: Loan discount (e.g., 9 * 10**16 for 9%)
            liquidation_discount: Liquidation discount (e.g., 6 * 10**16 for 6%)
            debt_ceiling: Maximum debt for this market (e.g., 10**6 * 10**18)
        
        Returns:
            Dictionary with 'controller' and 'amm' addresses
        """
        with boa.env.prank(self.admin):
            self.mint_factory.add_market(
                collateral_token.address,
                A,
                amm_fee,
                admin_fee,
                price_oracle.address,
                monetary_policy.address,
                loan_discount,
                liquidation_discount,
                debt_ceiling
            )
            
            controller_address = self.mint_factory.get_controller(collateral_token.address)
            amm_address = self.mint_factory.get_amm(collateral_token.address)
            
            return {
                'controller': controller_address,
                'amm': amm_address
            }
    
    def create_lending_market(
        self,
        borrowed_token: Any,
        collateral_token: Any,
        A: int,
        fee: int,
        loan_discount: int,
        liquidation_discount: int,
        price_oracle: Any,
        name: str,
        min_borrow_rate: int,
        max_borrow_rate: int
    ) -> Dict[str, Any]:
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
        
        Returns:
            Dictionary with 'vault', 'controller', 'amm', 'oracle', and 'monetary_policy' addresses
        """
        with boa.env.prank(self.admin):
            vault, controller, amm = self.lending_factory.create(
                borrowed_token.address,
                collateral_token.address,
                A,
                fee,
                loan_discount,
                liquidation_discount,
                price_oracle.address,
                name,
                min_borrow_rate,
                max_borrow_rate
            )
            
            return {
                'vault': vault,
                'controller': controller,
                'amm': amm
            }
    
    def get_deployed_contracts(self) -> Dict[str, Any]:
        """
        Get all deployed contracts in the protocol.
        
        Returns:
            Dictionary containing all deployed contract addresses
        """
        return {
            'admin': self.admin,
            'crvUSD': self.crvUSD,
            'weth': self.weth,
            'amm_impl': self.amm_impl,
            'price_oracle': self.price_oracle,
            'mint_factory': self.mint_factory,
            'mint_controller_impl': self.mint_controller_impl,
            'mint_monetary_policy': self.mint_monetary_policy,
            'lending_factory': self.lending_factory,
            'vault_impl': self.vault_impl,
            'll_controller_impl': self.ll_controller_impl,
            'price_oracle_impl': self.price_oracle_impl,
            'mpolicy_impl': self.mpolicy_impl
        }

if __name__ == "__main__":
    # import cProfile
    # import pstats
    
    # profiler = cProfile.Profile()
    # profiler.enable()
    
    proto = Protocol()
    collat = ERC20_MOCK_DEPLOYER.deploy(18)
    proto.create_mint_market(
        collat,
        proto.price_oracle,
        proto.mint_monetary_policy,
        A=1000,
        amm_fee=10**16,
        admin_fee=0,
        loan_discount= int(0.8 * 10**18),
        liquidation_discount=int(0.85 * 10**18),
        debt_ceiling=1000 * 10**18
    )
    
    # profiler.disable()
    # stats = pstats.Stats(profiler)
    # stats.dump_stats('protocol_deploy.prof')
    # print("Profile saved to protocol_deploy.prof")
    # print("Run: snakeviz protocol_deploy.prof")