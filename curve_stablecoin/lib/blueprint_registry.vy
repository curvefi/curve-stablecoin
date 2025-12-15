# pragma version 0.4.3

event BlueprintSet:
    blueprint_id: indexed(String[4])
    blueprint_address: address

MAX_LENGTH: constant(uint8) = 10
BLUEPRINT_REGISTRY_IDS: public(immutable(DynArray[String[4], MAX_LENGTH]))
_blueprints: HashMap[String[4], address]
# TODO add to linting coverage


@deploy
def __init__(_allowed_ids: DynArray[String[4], MAX_LENGTH]):
    BLUEPRINT_REGISTRY_IDS = _allowed_ids

@internal
@view
def in_array(_value: String[4], _array: DynArray[String[4], MAX_LENGTH]) -> bool:
    # The compiler does not have 'in' operator for DynArray.
    for item: String[4] in _array:
        if item == _value:
            return True
    return False


@internal
def set(_id: String[4], _address: address):
    assert self.in_array(_id, BLUEPRINT_REGISTRY_IDS) # dev: blueprint id not allowed
    self._blueprints[_id] = _address
    log BlueprintSet(blueprint_id=_id, blueprint_address=_address)


@internal
@view
def get(_id: String[4]) -> address:
    blueprint: address = self._blueprints[_id]
    assert blueprint != empty(address) # dev: blueprint not found
    return blueprint
