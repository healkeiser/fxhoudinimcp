"""Tests for HOM value coercion (fxhoudinimcp_server.serialize).

The module under test resolves HOM classes with isinstance(), so these tests
install a fake ``hou`` whose types are real classes -- a MagicMock attribute is
not a type and would make isinstance() raise.
"""

from __future__ import annotations

# Built-in
import importlib
import json
import os
import sys
import types

# Third-party
import pytest

###### Fake HOM

class _FakeVector(tuple):
    """Stands in for hou.Vector2/3/4: a fixed-length iterable of floats."""


class _FakeMatrix:
    def __init__(self, rows):
        self._rows = rows

    def asTupleOfTuples(self):
        return self._rows


class _FakeQuaternion(tuple):
    pass


class _FakeColor:
    def __init__(self, rgb):
        self._rgb = rgb

    def rgb(self):
        return self._rgb


class _FakeRampBasis:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeRamp:
    def __init__(self, keys, values, is_color=False, basis=("BSpline",)):
        self._keys, self._values = keys, values
        self._is_color, self._basis = is_color, basis

    def isColor(self):
        return self._is_color

    def basis(self):
        return tuple(_FakeRampBasis(b) for b in self._basis)

    def keys(self):
        return self._keys

    def values(self):
        return self._values


class _FakeGeometry:
    def __init__(self, counts):
        self._counts = counts

    def intrinsicValue(self, name):
        return self._counts[name]


class _FakeNode:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _FakeParm(_FakeNode):
    pass


class _Exploding:
    """Every accessor raises, to prove coercion never propagates."""

    def path(self):
        raise RuntimeError("nope")

    def asTupleOfTuples(self):
        raise RuntimeError("nope")

    def rgb(self):
        raise RuntimeError("nope")

    def __repr__(self):
        return "<Exploding>"


def _build_fake_hou():
    hou = types.ModuleType("hou")
    hou.Vector2 = hou.Vector3 = hou.Vector4 = _FakeVector
    hou.Matrix2 = hou.Matrix3 = hou.Matrix4 = _FakeMatrix
    hou.Quaternion = _FakeQuaternion
    hou.Color = _FakeColor
    hou.Ramp = _FakeRamp
    hou.Geometry = _FakeGeometry
    hou.Node = _FakeNode
    hou.Parm = _FakeParm
    # A callable, not a class -- stands in for the MagicMock attributes the
    # unit-test suite otherwise puts on `hou`.
    hou.notAClass = lambda path: None
    return hou


@pytest.fixture(scope="module")
def serialize():
    """Load serialize.py against the fake hou, then restore the real one.

    An explicit reload is required, not just a sys.modules swap: another test
    module imports the package first with `hou` mocked, and serialize.py
    resolves its HOM classes once at import time. Without the reload this
    fixture would hand back a module whose type tuples are all empty.
    """
    sys.path.insert(
        0,
        os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"),
    )
    saved_hou = sys.modules.get("hou")
    sys.modules["hou"] = _build_fake_hou()

    from fxhoudinimcp_server import serialize as module

    importlib.reload(module)
    try:
        yield module
    finally:
        if saved_hou is not None:
            sys.modules["hou"] = saved_hou
        else:
            sys.modules.pop("hou", None)
        # Leave the module as the rest of the suite expects to find it.
        try:
            importlib.reload(module)
        except ImportError:
            pass


###### JSON-native passthrough

class TestPassthrough:
    @pytest.mark.parametrize(
        "value", [None, True, False, 0, -3, 1.5, "", "text"]
    )
    def test_native_values_unchanged(self, serialize, value):
        assert serialize.to_jsonable(value) == value

    def test_bool_stays_bool(self, serialize):
        assert serialize.to_jsonable(True) is True

    def test_bytes_become_text(self, serialize):
        assert serialize.to_jsonable(b"hello") == "hello"

    def test_undecodable_bytes_do_not_raise(self, serialize):
        assert isinstance(serialize.to_jsonable(b"\xff\xfe"), str)


###### Containers

class TestContainers:
    def test_dict_keys_coerced_to_str(self, serialize):
        assert serialize.to_jsonable({1: "a", None: "b"}) == {"1": "a", "None": "b"}

    def test_nested_structures_walked(self, serialize):
        value = {"a": [{"b": (_FakeVector((1.0, 2.0)),)}]}
        assert serialize.to_jsonable(value) == {"a": [{"b": [[1.0, 2.0]]}]}

    def test_sets_become_lists(self, serialize):
        assert sorted(serialize.to_jsonable({3, 1, 2})) == [1, 2, 3]

    def test_tuple_becomes_list(self, serialize):
        assert serialize.to_jsonable((1, 2)) == [1, 2]

    def test_deep_nesting_is_capped(self, serialize):
        deep = current = {}
        for _ in range(50):
            current["n"] = {}
            current = current["n"]
        # Must terminate and stay JSON-encodable rather than recursing forever.
        assert json.dumps(serialize.to_jsonable(deep))

    def test_self_referential_dict_terminates(self, serialize):
        value = {}
        value["self"] = value
        assert json.dumps(serialize.to_jsonable(value))


###### HOM types

class TestHomTypes:
    def test_vector_becomes_list(self, serialize):
        assert serialize.to_jsonable(_FakeVector((1.0, 2.0, 3.0))) == [1.0, 2.0, 3.0]

    def test_matrix_becomes_list_of_rows(self, serialize):
        matrix = _FakeMatrix(((1.0, 0.0), (0.0, 1.0)))
        assert serialize.to_jsonable(matrix) == [[1.0, 0.0], [0.0, 1.0]]

    def test_color_becomes_rgb_list(self, serialize):
        assert serialize.to_jsonable(_FakeColor((0.1, 0.2, 0.3))) == [0.1, 0.2, 0.3]

    def test_node_becomes_path(self, serialize):
        assert serialize.to_jsonable(_FakeNode("/obj/geo1")) == "/obj/geo1"

    def test_parm_becomes_path(self, serialize):
        assert serialize.to_jsonable(_FakeParm("/obj/geo1/tx")) == "/obj/geo1/tx"

    def test_geometry_becomes_counts(self, serialize):
        geo = _FakeGeometry(
            {"pointcount": 8, "primitivecount": 6, "vertexcount": 24}
        )
        assert serialize.to_jsonable(geo) == {
            "type": "Geometry",
            "point_count": 8,
            "prim_count": 6,
            "vertex_count": 24,
        }

    def test_enum_like_uses_name(self, serialize):
        assert serialize.to_jsonable(_FakeRampBasis("Linear")) == "Linear"


###### Ramps -- the actual subject of issue #15

class TestRamp:
    def test_float_ramp_is_structured(self, serialize):
        ramp = _FakeRamp(
            keys=(0.0, 1.0), values=(0.25, 0.75), basis=("BSpline", "Linear")
        )
        assert serialize.to_jsonable(ramp) == {
            "type": "Ramp",
            "is_color": False,
            "basis": ["BSpline", "Linear"],
            "keys": [0.0, 1.0],
            "values": [0.25, 0.75],
        }

    def test_colour_ramp_values_become_lists(self, serialize):
        ramp = _FakeRamp(
            keys=(0.0, 1.0),
            values=((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            is_color=True,
        )
        result = serialize.to_jsonable(ramp)
        assert result["is_color"] is True
        assert result["values"] == [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]

    def test_ramp_is_json_encodable(self, serialize):
        """The regression: a Ramp used to raise inside json.dumps."""
        ramp = _FakeRamp(keys=(0.0,), values=(1.0,))
        assert json.loads(json.dumps(serialize.to_jsonable(ramp)))["type"] == "Ramp"


###### Degradation

class TestDegradation:
    def test_unknown_object_becomes_repr(self, serialize):
        result = serialize.to_jsonable(object())
        assert isinstance(result, str) and "object" in result

    def test_repr_is_truncated(self, serialize):
        class _Huge:
            def __repr__(self):
                return "x" * 10_000

        assert len(serialize.to_jsonable(_Huge())) <= serialize._MAX_REPR

    def test_failing_accessors_do_not_raise(self, serialize):
        assert serialize.to_jsonable(_Exploding()) == "<Exploding>"

    def test_ramp_with_failing_accessors_still_returns_dict(self, serialize):
        class _BadRamp(_FakeRamp):
            def keys(self):
                raise RuntimeError("nope")

        result = serialize.to_jsonable(_BadRamp(keys=(), values=()))
        assert result["type"] == "Ramp" and "keys" not in result

    def test_geometry_with_missing_intrinsics_still_returns_dict(self, serialize):
        result = serialize.to_jsonable(_FakeGeometry({}))
        assert result == {"type": "Geometry"}


###### The json.dumps hook

class TestJsonDefault:
    def test_hook_makes_dumps_succeed(self, serialize):
        payload = {
            "ramp": _FakeRamp(keys=(0.0,), values=(1.0,)),
            "node": _FakeNode("/obj/geo1"),
            "junk": object(),
        }
        with pytest.raises(TypeError):
            json.dumps(payload)

        decoded = json.loads(json.dumps(payload, default=serialize.json_default))
        assert decoded["ramp"]["type"] == "Ramp"
        assert decoded["node"] == "/obj/geo1"
        assert isinstance(decoded["junk"], str)

    def test_hook_never_returns_unserialisable(self, serialize):
        assert json.dumps(serialize.json_default(_Exploding()))


###### Defensive type resolution

class TestTypeResolution:
    def test_missing_hou_classes_are_skipped(self, serialize):
        assert serialize._hou_types("NoSuchHomClass") == ()

    def test_non_class_attributes_are_skipped(self, serialize):
        """Guards the mocked-hou case: a MagicMock attribute is not a type."""
        assert serialize._hou_types("notAClass") == ()

    def test_resolution_keeps_the_classes_that_do_exist(self, serialize):
        assert serialize._hou_types("Ramp", "NoSuchHomClass") == (_FakeRamp,)
