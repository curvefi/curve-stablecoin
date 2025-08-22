import boa


def mint_for_testing(token, to, amount):
    boa.deal(token, to, token.balanceOf(to) + amount)
