"""Type system and explicit safe type conversions for GQL-Core.

Defines:
- DataType enum: ANY, STRING, INTEGER, FLOAT, BOOLEAN, DATE, TIME, DATETIME, DURATION, INTERVAL, LIST, MAP, NODE, EDGE, UNKNOWN
- Type validation, checking, and conversion utilities.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from gql_core.temporal import Date, DateTime, Duration, Interval, Time, coerce_temporal


class DataType(str, Enum):
    ANY = "ANY"
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    TIME = "TIME"
    DATETIME = "DATETIME"
    DURATION = "DURATION"
    INTERVAL = "INTERVAL"
    LIST = "LIST"
    MAP = "MAP"
    NODE = "NODE"
    EDGE = "EDGE"
    UNKNOWN = "UNKNOWN"


class TypeErrorDiagnostic(TypeError):
    """Raised when strict type checking fails or illegal conversions are attempted."""


def infer_data_type(val: Any) -> DataType:
    """Infer the DataType of a Python object."""
    if val is None:
        return DataType.UNKNOWN
    # Note: in Python, bool is a subclass of int, so check bool first!
    if isinstance(val, bool):
        return DataType.BOOLEAN
    if isinstance(val, int):
        return DataType.INTEGER
    if isinstance(val, float):
        return DataType.FLOAT
    if isinstance(val, str):
        return DataType.STRING
    if isinstance(val, Date):
        return DataType.DATE
    if isinstance(val, Time):
        return DataType.TIME
    if isinstance(val, DateTime):
        return DataType.DATETIME
    if isinstance(val, Duration):
        return DataType.DURATION
    if isinstance(val, Interval):
        return DataType.INTERVAL
    if isinstance(val, (list, tuple)):
        return DataType.LIST
    if isinstance(val, dict):
        return DataType.MAP
    # Graph entities check by class name to avoid circular import
    cls_name = type(val).__name__
    if cls_name == "Node":
        return DataType.NODE
    if cls_name == "Edge":
        return DataType.EDGE
    return DataType.ANY


def is_numeric_type(t: DataType) -> bool:
    return t in (DataType.INTEGER, DataType.FLOAT)


def is_temporal_type(t: DataType) -> bool:
    return t in (DataType.DATE, DataType.TIME, DataType.DATETIME, DataType.DURATION, DataType.INTERVAL)


def check_type_compatibility(val: Any, expected: DataType) -> bool:
    """Return True if val is compatible with expected DataType."""
    if expected == DataType.ANY or val is None:
        return True
    actual = infer_data_type(val)
    if expected == DataType.FLOAT and actual == DataType.INTEGER:
        return True
    return actual == expected


# Safe explicit conversions
def cast_to_integer(val: Any) -> int:
    if val is None:
        raise TypeErrorDiagnostic("Cannot cast null to INTEGER")
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise TypeErrorDiagnostic(f"Cannot cast NaN or Infinity to INTEGER: {val}")
        return int(val)
    if isinstance(val, str):
        try:
            return int(val.strip())
        except ValueError as e:
            raise TypeErrorDiagnostic(f"Invalid string for INTEGER conversion: {val!r}") from e
    raise TypeErrorDiagnostic(f"Cannot cast {type(val).__name__} to INTEGER")


def cast_to_float(val: Any) -> float:
    if val is None:
        raise TypeErrorDiagnostic("Cannot cast null to FLOAT")
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError as e:
            raise TypeErrorDiagnostic(f"Invalid string for FLOAT conversion: {val!r}") from e
    raise TypeErrorDiagnostic(f"Cannot cast {type(val).__name__} to FLOAT")


def cast_to_string(val: Any) -> str:
    if val is None:
        return "null"
    return str(val)


def cast_to_boolean(val: Any) -> bool:
    if val is None:
        raise TypeErrorDiagnostic("Cannot cast null to BOOLEAN")
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        raise TypeErrorDiagnostic(f"Cannot parse boolean from string: {val!r}")
    raise TypeErrorDiagnostic(f"Cannot cast {type(val).__name__} to BOOLEAN")


def cast_to_date(val: Any) -> Date:
    if isinstance(val, Date):
        return val
    if isinstance(val, str):
        return Date.from_iso(val)
    raise TypeErrorDiagnostic(f"Cannot cast {type(val).__name__} to DATE")


def cast_to_datetime(val: Any) -> DateTime:
    if isinstance(val, DateTime):
        return val
    if isinstance(val, str):
        return DateTime.from_iso(val)
    raise TypeErrorDiagnostic(f"Cannot cast {type(val).__name__} to DATETIME")
