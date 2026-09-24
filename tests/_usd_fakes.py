"""Minimal pxr stand-ins shared by the USD handler tests."""

from __future__ import annotations

# Built-in
from unittest.mock import MagicMock


class Path:
    """Enough of Sdf.Path: str(), element-wise prefix and element count."""

    def __init__(self, text):
        self.text = text
        self.elements = [e for e in text.split("/") if e]

    @property
    def pathElementCount(self):
        return len(self.elements)

    def HasPrefix(self, other):
        return self.elements[: len(other.elements)] == other.elements

    def __str__(self):
        return self.text


def prim(path, valid=True, type_name="Xform"):
    """A Usd.Prim at *path*; falsy and invalid when *valid* is False."""
    fake = MagicMock()
    fake.GetPath.return_value = Path(path)
    fake.GetTypeName.return_value = type_name
    fake.IsValid.return_value = valid
    fake.__bool__ = lambda self: valid
    return fake


def attribute(name, default=None, samples=None, type_name="int2"):
    """A Usd.Attribute with a default slot and optional {frame: value} samples.

    Get() takes a time code whose `value` is the frame (None for the default
    time code) and holds the last sample at or before it, as USD does.
    """
    samples = dict(samples or {})

    def get(time_code=None):
        frame = getattr(time_code, "value", None)
        if frame is None or not samples:
            return default
        keys = sorted(samples)
        return samples[max((k for k in keys if k <= frame), default=keys[0])]

    fake = MagicMock()
    fake.GetName.return_value = name
    fake.GetTypeName.return_value = type_name
    fake.IsAuthored.return_value = True
    fake.HasValue.return_value = True
    fake.GetNumTimeSamples.return_value = len(samples)
    fake.Get.side_effect = get
    return fake


def relationship(name, targets=()):
    """A Usd.Relationship pointing at *targets*."""
    fake = MagicMock()
    fake.GetName.return_value = name
    fake.GetTargets.return_value = [Path(t) for t in targets]
    return fake


def prim_with(path, type_name="Xform", attributes=(), relationships=()):
    """A plain (not instanceable) prim carrying *attributes* and *relationships*."""
    fake = prim(path, type_name=type_name)
    fake.IsInstanceable.return_value = False
    fake.IsInstanceProxy.return_value = False
    fake.GetAttributes.return_value = list(attributes)
    fake.GetRelationships.return_value = list(relationships)
    return fake


def usd_module():
    """A pxr.Usd stand-in whose time codes carry their frame as `value`."""
    usd = MagicMock()
    usd.TimeCode.side_effect = lambda t: MagicMock(value=t)
    usd.TimeCode.Default.return_value = MagicMock(value=None)
    usd.ModelAPI.return_value = None
    return usd
