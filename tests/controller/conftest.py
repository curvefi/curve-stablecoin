from pytest import fixture

# Common fixtures (proto, admin) are now in tests/conftest.py


@fixture(scope="module", params=[2, 6, 8, 9, 18])
def decimals(request):
    return request.param
