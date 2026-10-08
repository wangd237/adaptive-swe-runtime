from aswe.core.fingerprint import canonical_json_bytes, fingerprint

def test_fingerprint_is_dict_order_independent()->None:
    left={"b":[2,1],"a":{"z":True,"x":"值"}}
    right={"a":{"x":"值","z":True},"b":[2,1]}
    assert canonical_json_bytes(left)==canonical_json_bytes(right)
    assert fingerprint(left)==fingerprint(right)

def test_sequence_order_remains_semantic()->None:
    assert fingerprint([1,2])!=fingerprint([2,1])
