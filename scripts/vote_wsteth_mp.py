import sys
import boa
import networks
import curve_dao
from curve_dao.addresses import CURVE_DAO_OWNERSHIP as target


TOKEN = "wstETH"
CONTROLLER = "0x5756A035F276a8095A922931F224F4ed06149608"
MPOLICY = "0xbc7507bEA8d7bcb49f511cf59651B5114e6E7667"


if __name__ == '__main__':
    if '--fork' in sys.argv[1:]:
        boa.env.fork(networks.NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_network_env(networks.NETWORK)
        babe = boa.env.add_accounts_from_rpc("http://localhost:1248")

    controller_impl = boa.load_partial('contracts/Controller.vy')

    actions = [
        (controller_impl.at(CONTROLLER), 'set_monetary_policy', MPOLICY)
    ]
    vote_id = curve_dao.create_vote(
        target,
        actions,
        f"Set secondary monetary policy for the new {TOKEN} LlamaLend market",
        networks.ETHERSCAN_API_KEY,
        networks.PINATA_TOKEN
    )
    print(vote_id)

    if '--fork' in sys.argv[1:]:
        # Simulating the vote
        assert curve_dao.simulate(vote_id, target['voting'], networks.ETHERSCAN_API_KEY)
