import pytest
from aswe.core.ids import new_execution_id, new_preparation_id, new_task_id, validate_safe_id

def test_generated_ids_are_safe()->None:
    for value in (new_task_id(),new_execution_id(),new_preparation_id()):
        assert validate_safe_id(value)==value
        assert ":" not in value
        assert "/" not in value

def test_external_unsafe_id_is_rejected()->None:
    with pytest.raises(ValueError):
        validate_safe_id("../../external:user")
