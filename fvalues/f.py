import ast
import inspect
import warnings
from copy import deepcopy
from dataclasses import dataclass
from types import FrameType
from typing import Any

import executing


@dataclass
class FValue:
    source: str
    value: Any
    formatted: str


Part = str | FValue
Parts = tuple[Part, ...]


class F(str):
    def __new__(cls, s: str, parts: Parts = None):
        if parts is not None:
            expected = "".join(
                part.formatted if isinstance(part, FValue) else part for part in parts
            )
            assert s == expected, f"{s!r} != {expected!r}"
            result = super().__new__(cls, s)
            result.parts = parts
            return result

        frame = inspect.currentframe().f_back
        ex = executing.Source.executing(frame)
        if ex.node is None:
            warnings.warn("Couldn't get source node of F() call")
            return F(s, (s,))

        if not isinstance(ex.node, ast.Call):
            raise TypeError("F must be called directly, nothing fancy")
        [arg] = ex.node.args
        return F(s, F._parts_from_node(arg, frame, s))

    @staticmethod
    def _parts_from_node(node: ast.expr, frame: FrameType, value: Part | None) -> Parts:
        if isinstance(node, ast.Constant):
            assert isinstance(node.value, str)
            return (node.value,)
        elif isinstance(node, ast.JoinedStr):
            parts: list[Part] = []
            for node in node.values:
                parts.extend(F._parts_from_node(node, frame, None))
            return tuple(parts)
        elif isinstance(node, ast.FormattedValue):
            source = ast.unparse(node.value)
            # TODO cache compiled code?
            value = eval(source, frame.f_globals, frame.f_locals)
            expr = ast.Expression(ast.JoinedStr(values=[node]))
            ast.fix_missing_locations(expr)  # noqa
            # TODO this evals the value again just for the sake of a formatted value
            code = compile(expr, "<ast>", "eval")  # noqa
            formatted = eval(code, frame.f_globals, frame.f_locals)
            f_value = FValue(source, value, formatted)
            return (f_value,)
        else:
            assert isinstance(value, str)
            f_value = FValue(ast.unparse(node), value, value)
            return (f_value,)

    def __deepcopy__(self, memodict=None):
        return F(str(self), deepcopy(self.parts, memodict))

    def flatten(self) -> "F":
        parts: list[Part] = []
        for part in self.parts:
            if isinstance(part, FValue) and isinstance(part.value, F):
                parts.extend(part.value.flatten().parts)
            elif isinstance(part, F):
                parts.extend(part.flatten().parts)
            else:
                parts.append(part)
        return F(str(self), tuple(parts))

    def strip(self, *args) -> "F":
        return self.lstrip(*args).rstrip(*args)

    def lstrip(self, *args) -> "F":
        return self._strip(0, "lstrip", *args)

    def rstrip(self, *args) -> "F":
        return self._strip(-1, "rstrip", *args)

    def _strip(self, index: int, method: str, *args) -> "F":
        parts = list(self.parts)
        while True:
            part = parts[index]
            if isinstance(part, FValue):
                s = part.formatted
            else:
                s = part
            s = getattr(s, method)(*args)
            if s:
                if isinstance(part, FValue):
                    part = FValue(part.source, part.value, s)
                else:
                    part = s
                parts[index] = part
                break
            else:
                del parts[index]
        s = getattr(super(), method)(*args)
        return F(s, tuple(parts))

    def _add(self, other, is_left: bool):
        parts = (self, other) if is_left else (other, self)
        value = str(parts[0]) + str(parts[1])
        frame = inspect.currentframe().f_back.f_back
        node = executing.Source.executing(frame).node
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(
            node.op, ast.Add
        ):
            if isinstance(node, ast.AugAssign):
                left_node = node.target
                right_node = node.value
            else:
                left_node = node.left
                right_node = node.right
            left_parts = F._parts_from_node(left_node, frame, parts[0])
            right_parts = F._parts_from_node(right_node, frame, parts[1])
            parts = left_parts + right_parts

        return F(value, parts)

    def __add__(self, other):
        return self._add(other, True)

    def __radd__(self, other):
        return self._add(other, False)
