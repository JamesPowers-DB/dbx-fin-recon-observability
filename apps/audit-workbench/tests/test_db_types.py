"""fetch_all must return plain lists and dicts however the connector delivers complex types.

databricks-sql-connector with pyarrow (the Apps runtime): ARRAY -> numpy.ndarray,
MAP -> list of (key, value) tuples, STRUCT -> dict holding those. Without pyarrow:
all three arrive as JSON strings. The deployed app broke on the first form while the
local Statement Execution shim only ever produced lists and dicts.
"""
from decimal import Decimal

import numpy as np

from backend.db import _column


def test_array_from_numpy_is_a_list():
    v = _column(np.array(["JET-01", "JET-05"], dtype=object), "array")
    assert v == ["JET-01", "JET-05"] and type(v) is list
    assert (v or []) == v  # the expression that raised "truth value ... is ambiguous"


def test_numeric_array_elements_are_python_numbers():
    v = _column(np.array([1, 2], dtype=np.int32), "array")
    assert v == [1, 2] and all(type(x) is int for x in v)


def test_map_from_tuple_list_is_a_dict():
    v = _column([("je_header_id", "42"), ("user_id", "7")], "map")
    assert v == {"je_header_id": "42", "user_id": "7"}
    assert v.get("je_header_id") == "42"


def test_empty_map_is_an_empty_dict():
    assert _column([], "map") == {}


def test_struct_with_nested_array_and_decimal():
    v = _column({"x": 1, "ys": np.array([1, 2], dtype=np.int32), "d": Decimal("2.5")}, "struct")
    assert v == {"x": 1, "ys": [1, 2], "d": 2.5}


def test_array_of_structs():
    v = _column(np.array([{"k": "v", "n": Decimal("2.5")}], dtype=object), "array")
    assert v == [{"k": "v", "n": 2.5}]


def test_json_strings_without_pyarrow():
    assert _column('["a","b"]', "array") == ["a", "b"]
    assert _column('{"je_header_id":"42"}', "map") == {"je_header_id": "42"}
    assert _column('{"x":1,"ys":[1,2]}', "struct") == {"x": 1, "ys": [1, 2]}


def test_scalars_unchanged_and_decimal_to_float():
    assert _column("CASH-02", "string") == "CASH-02"
    assert _column(Decimal("1.50"), "decimal") == 1.5
    assert _column(None, "array") is None
    assert _column(7, "bigint") == 7
