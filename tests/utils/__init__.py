import boa


def mint_for_testing(token, to, amount):
    # DO NOT USE: this is an old function for backwards compatibility.
    # When you need this just inline this boa behavior.
    boa.deal(token, to, token.balanceOf(to) + amount)


def filter_logs(contract, event_name, _strict=False):
    return [
        e for e in contract.get_logs(strict=_strict) if type(e).__name__ == event_name
    ]
