import boa
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, rule


class BigFuzz(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.anchor = boa.env.anchor()
        self.anchor.__enter__()

    @rule()
    def something(self):
        pass

    def teardown(self):
        self.anchor.__exit__(None, None, None)


BigFuzz.TestCase.settings = settings(max_examples=10, stateful_step_count=10)
TestBigFuzz = BigFuzz.TestCase
