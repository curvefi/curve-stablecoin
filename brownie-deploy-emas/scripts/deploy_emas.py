from brownie import network, accounts
from brownie import ChainlinkEMA


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
    args = {'from': babe, 'priority_fee': 'auto'}
    print(f'Deploying on {current_network}')

    for name, feed in feed_list:
        oracle = ChainlinkEMA.deploy(feed, OBSERVATIONS, INTERVAL, args, publish_source=True)
        print(f'{name}: {oracle.address} - {oracle.price() / 1e18}')
