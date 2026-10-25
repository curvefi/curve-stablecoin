import boa
import pytest

from tests.utils.constants import ZERO_ADDRESS


def test_is_killed_before_attachment(
    admin, amm, controller, configurator, deploy_lm_callback
):
    with boa.env.anchor():
        callback = deploy_lm_callback(amm)
        assert callback.is_killed()
        assert not callback.attached()
        assert not callback.detached()

        configurator.set_callback(controller, callback, sender=admin)
        assert not callback.is_killed()
        # Reading the flag must not change the attachment bookkeeping.
        assert not callback.attached()


@pytest.mark.parametrize("checkpoint", [False, True])
def test_is_killed_while_attached(lm_callback, checkpoint):
    with boa.env.anchor():
        if checkpoint:
            lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert not lm_callback.is_killed()


@pytest.mark.parametrize("replacement", [ZERO_ADDRESS, "other_callback"])
def test_is_killed_on_detach(admin, controller, configurator, lm_callback, replacement):
    with boa.env.anchor():
        lm_callback.user_checkpoint(ZERO_ADDRESS)
        if replacement == "other_callback":
            replacement = boa.env.generate_address("other_callback")
        configurator.set_callback(controller, replacement, sender=admin)

        assert lm_callback.is_killed()
        assert not lm_callback.detached()

        lm_callback.user_checkpoint(ZERO_ADDRESS)
        assert lm_callback.detached()
        assert lm_callback.is_killed()

        configurator.set_callback(controller, lm_callback, sender=admin)
        assert lm_callback.is_killed()
