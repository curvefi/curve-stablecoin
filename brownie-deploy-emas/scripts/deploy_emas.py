from brownie import network, accounts
from brownie import ChainlinkEMA

# Deployed oracles:
#
# Optimism
# ETH: 0x92577943c7aC4accb35288aB2CC84D75feC330aF - 2527.677385278486
# wstETH: 0x44343B1B95BaA53eC561F8d7B357155B89507077 - 2973.64312578
# WBTC: 0xEc12C072d9ABdf3F058C8B17169eED334fC1dE58 - 59936.0695874035
# OP: 0x3Fa8ebd5d16445b42e0b6A54678718C94eA99aBC - 1.4259036116957085
# CRV: 0x2016f1AaE491438E6EA908e30b60dAeb56ac185c - 0.30310084862222325
# VELO: 0xc820FA08406174c14AA29335AbFbaf6B147B3D4c - 0.08164874


OBSERVATIONS = 20
INTERVAL = 30

FEEDS = {
    'optimism-main': [
        ('ETH', '0x13e3Ee699D1909E989722E753853AE30b17e08c5'),
        ('wstETH', '0x698B585CbC4407e2D54aa898B2600B53C68958f7'),
        ('WBTC', '0x718A5788b89454aAE3A028AE9c111A29Be6c2a6F'),
        ('OP', '0x0D276FC14719f9292D5C1eA2198673d1f4269246'),
        ('CRV', '0xbD92C6c284271c227a1e0bF1786F468b539f51D9'),
        ('VELO', '0x0f2Ed59657e391746C1a097BDa98F2aBb94b1120'),
    ],
    'fraxtal-main': [
        ('ETH', '0x89e60b56efD70a1D4FBBaE947bC33cae41e37A72'),
        ('FRAX', '0xa41107f9259bB835275eaCaAd8048307B80D7c00'),
        ('FXS', '0xbf228a9131AB3BB8ca8C7a4Ad574932253D99Cd1'),
        ('CRV', '0x6C5090e85a65038ca6AB207CDb9e7a897cb33e4d'),
    ]
}


def main():
    babe = accounts.load('babe')
    current_network = network.show_active()
    feed_list = FEEDS[current_network]
    args = {'from': babe, 'priority_fee': 'auto', 'required_confs': 5}
    print(f'Deploying on {current_network}')

    for name, feed in feed_list:
        oracle = ChainlinkEMA.deploy(feed, OBSERVATIONS, INTERVAL, args, publish_source=False)
        print(f'{name}: {oracle.address} - {oracle.price() / 1e18}')
