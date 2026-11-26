"""Deterministic translation of Tableau calculation formulas to Databricks SQL, for reference values.

It covers the common subset (IF/CASE, IIF, ZN, aggregates, dates, strings, arithmetic, references to other
calculations and to parameters) and refuses everything else with a reason: LOD expressions, table
calculations, other datasources, and unknown functions. A refusal makes a measure "not comparable"; the
translation never guesses. It is independent of the Genie import, so agreement on the same data is evidence.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .metric_compiler import TABLE_CALCULATION_FUNCTIONS, tokenize_formula

MAXIMUM_DEPTH = 25
KEYWORDS = {
    "IF": "CASE WHEN", "ELSEIF": "WHEN", "THEN": "THEN", "ELSE": "ELSE", "END": "END", "CASE": "CASE",
    "WHEN": "WHEN", "AND": "AND", "OR": "OR", "NOT": "NOT", "TRUE": "TRUE", "FALSE": "FALSE", "NULL": "NULL",
    "IN": "IN",
}
DATE_UNITS = {"year", "quarter", "month", "week", "day", "hour", "minute", "second"}
DATE_TYPES = {"date", "datetime"}
# Functions whose result is a date, for Tableau's date - date (a number of days).
DATE_FUNCTIONS = {"DATE", "DATEADD", "DATETRUNC", "MAKEDATE", "TODAY", "NOW"}
SQL_AGGREGATE_PATTERN = re.compile(
    r"\b(SUM|AVG|COUNT|MIN|MAX|MEDIAN|STDDEV_SAMP|STDDEV_POP|VAR_SAMP|VAR_POP)\s*\(", re.IGNORECASE
)


class Untranslatable(ValueError):
    """The formula uses something the translation does not support; the message says what."""


def _quote(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _string_literal(token: str) -> str:
    body = token[1:-1]
    quote_character = token[0]
    body = body.replace("\\" + quote_character, quote_character).replace("\\\\", "\\")
    return "'" + body.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _unit(argument: str) -> str:
    unit = argument.strip().strip("'\"").casefold()
    if unit not in DATE_UNITS:
        raise Untranslatable(f"date part {argument} is not supported")
    return unit


def _arguments(count: range, name: str, arguments: list[str]) -> list[str]:
    if len(arguments) not in count:
        raise Untranslatable(f"{name} with {len(arguments)} argument(s) is not supported")
    return arguments


def _aggregate(sql_name: str) -> Callable[[list[str]], str]:
    return lambda arguments: f"{sql_name}({_arguments(range(1, 2), sql_name, arguments)[0]})"


def _same(name: str, counts: range) -> Callable[[list[str]], str]:
    return lambda arguments: f"{name}({', '.join(_arguments(counts, name, arguments))})"


def _min_max(name: str, two_argument: str) -> Callable[[list[str]], str]:
    def translate(arguments: list[str]) -> str:
        _arguments(range(1, 3), name, arguments)
        return f"{name}({arguments[0]})" if len(arguments) == 1 else f"{two_argument}({', '.join(arguments)})"

    return translate


def _iif(arguments: list[str]) -> str:
    _arguments(range(3, 5), "IIF", arguments)
    return f"CASE WHEN {arguments[0]} THEN {arguments[1]} ELSE {arguments[2]} END"


def _log(arguments: list[str]) -> str:
    _arguments(range(1, 3), "LOG", arguments)
    return f"LOG10({arguments[0]})" if len(arguments) == 1 else f"LOG({arguments[1]}, {arguments[0]})"


def _mid(arguments: list[str]) -> str:
    _arguments(range(2, 4), "MID", arguments)
    return f"SUBSTRING({', '.join(arguments)})"


FUNCTIONS: dict[str, Callable[[list[str]], str]] = {
    "SUM": _aggregate("SUM"),
    "AVG": _aggregate("AVG"),
    "COUNT": _aggregate("COUNT"),
    "COUNTD": lambda a: f"COUNT(DISTINCT {_arguments(range(1, 2), 'COUNTD', a)[0]})",
    "MEDIAN": _aggregate("MEDIAN"),
    "STDEV": _aggregate("STDDEV_SAMP"),
    "STDEVP": _aggregate("STDDEV_POP"),
    "VAR": _aggregate("VAR_SAMP"),
    "VARP": _aggregate("VAR_POP"),
    "MIN": _min_max("MIN", "LEAST"),
    "MAX": _min_max("MAX", "GREATEST"),
    "ATTR": lambda a: f"CASE WHEN MIN({a[0]}) = MAX({a[0]}) THEN MIN({a[0]}) END",
    "ZN": lambda a: f"COALESCE({_arguments(range(1, 2), 'ZN', a)[0]}, 0)",
    "IFNULL": lambda a: f"COALESCE({', '.join(_arguments(range(2, 3), 'IFNULL', a))})",
    "ISNULL": lambda a: f"({_arguments(range(1, 2), 'ISNULL', a)[0]} IS NULL)",
    "IIF": _iif,
    "ABS": _same("ABS", range(1, 2)),
    "ROUND": _same("ROUND", range(1, 3)),
    "FLOOR": _same("FLOOR", range(1, 2)),
    "CEILING": lambda a: f"CEIL({_arguments(range(1, 2), 'CEILING', a)[0]})",
    "POWER": _same("POWER", range(2, 3)),
    "SQRT": _same("SQRT", range(1, 2)),
    "EXP": _same("EXP", range(1, 2)),
    "LN": _same("LN", range(1, 2)),
    "LOG": _log,
    "SIGN": _same("SIGN", range(1, 2)),
    "PI": lambda a: "PI()",
    "LEN": lambda a: f"LENGTH({_arguments(range(1, 2), 'LEN', a)[0]})",
    "LEFT": _same("LEFT", range(2, 3)),
    "RIGHT": _same("RIGHT", range(2, 3)),
    "MID": _mid,
    "UPPER": _same("UPPER", range(1, 2)),
    "LOWER": _same("LOWER", range(1, 2)),
    "TRIM": _same("TRIM", range(1, 2)),
    "LTRIM": _same("LTRIM", range(1, 2)),
    "RTRIM": _same("RTRIM", range(1, 2)),
    "CONTAINS": _same("CONTAINS", range(2, 3)),
    "STARTSWITH": _same("STARTSWITH", range(2, 3)),
    "ENDSWITH": _same("ENDSWITH", range(2, 3)),
    "REPLACE": _same("REPLACE", range(3, 4)),
    "FIND": lambda a: f"INSTR({', '.join(_arguments(range(2, 3), 'FIND', a))})",
    "STR": lambda a: f"CAST({_arguments(range(1, 2), 'STR', a)[0]} AS STRING)",
    "INT": lambda a: f"CAST({_arguments(range(1, 2), 'INT', a)[0]} AS INT)",
    "FLOAT": lambda a: f"CAST({_arguments(range(1, 2), 'FLOAT', a)[0]} AS DOUBLE)",
    "DATE": lambda a: f"TO_DATE({_arguments(range(1, 2), 'DATE', a)[0]})",
    "YEAR": _same("YEAR", range(1, 2)),
    "QUARTER": _same("QUARTER", range(1, 2)),
    "MONTH": _same("MONTH", range(1, 2)),
    "DAY": _same("DAY", range(1, 2)),
    "TODAY": lambda a: "CURRENT_DATE()",
    "NOW": lambda a: "CURRENT_TIMESTAMP()",
    "MAKEDATE": _same("MAKE_DATE", range(3, 4)),
    "DATEPART": lambda a: f"DATE_PART('{_unit(_arguments(range(2, 3), 'DATEPART', a)[0])}', {a[1]})",
    "DATETRUNC": lambda a: f"DATE_TRUNC('{_unit(_arguments(range(2, 3), 'DATETRUNC', a)[0])}', {a[1]})",
    # Databricks returns BIGINT; Tableau date arithmetic such as [Date] - DATEDIFF(...) needs INT.
    "DATEDIFF": lambda a: f"CAST(DATEDIFF({_unit(_arguments(range(3, 4), 'DATEDIFF', a)[0]).upper()}, {a[1]}, {a[2]}) AS INT)",
    "DATEADD": lambda a: f"DATEADD({_unit(_arguments(range(3, 4), 'DATEADD', a)[0]).upper()}, {a[1]}, {a[2]})",
}


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").casefold()).strip("_")


class FormulaTranslator:
    """Translates the calculations of one parsed Tableau datasource over one extract's columns."""

    def __init__(self, datasource_ir: dict[str, Any], extract_columns: list[str]):
        self.extract_by_key = {_key(name): name for name in extract_columns}
        # Tableau formulas name fields and calculations by internal ID; captions are only a fallback, because a
        # calculation may carry a field's caption (a calculation captioned Order Date that shifts [Order Date]).
        self.fields_by_id = {str(f.get("field_id")).casefold(): f for f in datasource_ir.get("fields", []) if f.get("field_id")}
        self.calculations_by_id = {
            str(c.get("calculation_id")).casefold(): c for c in datasource_ir.get("calculations", []) if c.get("calculation_id")
        }
        self.fields_by_caption: dict[str, dict[str, Any]] = {}
        for field in datasource_ir.get("fields", []):
            self.fields_by_caption.setdefault(f"[{field.get('name')}]".casefold(), field)
        self.calculations_by_caption: dict[str, dict[str, Any]] = {}
        for calculation in datasource_ir.get("calculations", []):
            self.calculations_by_caption.setdefault(f"[{calculation.get('name')}]".casefold(), calculation)
        self.parameters = {
            str(item.get("parameter_id", "")).casefold(): item for item in datasource_ir.get("parameters", [])
        }
        for item in datasource_ir.get("parameters", []):
            self.parameters.setdefault(f"[{item.get('name')}]".casefold(), item)

    def field_column(self, field: dict[str, Any]) -> str:
        for name in (field.get("name"), field.get("remote_name")):
            if _key(name) in self.extract_by_key:
                return _quote(self.extract_by_key[_key(name)])
        raise Untranslatable(f"field {field.get('name')!r} is not in the extract")

    def translate(self, formula: str, *, depth: int = 0, seen: frozenset[str] = frozenset()) -> str:
        if depth > MAXIMUM_DEPTH:
            raise Untranslatable("calculations are nested too deeply")
        # The shared tokenizer returns whitespace as symbols; it carries no meaning here.
        tokens = [(token.type, str(token)) for token in tokenize_formula(formula or "") if str(token).strip()]
        sql, position, _ = self._sequence(tokens, 0, depth=depth, seen=seen, stop=set())
        if position != len(tokens):
            raise Untranslatable(f"unexpected {tokens[position][1]!r}")
        return sql

    def _resolve(self, name: str, seen: frozenset[str]) -> tuple[str, dict[str, Any]] | None:
        """("calculation" | "field", definition) for a formula reference: IDs first, then captions.

        Inside a calculation's own formula, its ID means the field it replaces (a calculation whose ID is
        [Order Date] and whose formula shifts [Order Date]).
        """
        key = name.casefold()
        for kind, table in (
            ("calculation", self.calculations_by_id),
            ("field", self.fields_by_id),
            ("calculation", self.calculations_by_caption),
            ("field", self.fields_by_caption),
        ):
            item = table.get(key)
            if item is None:
                continue
            if kind == "calculation" and str(item.get("calculation_id", "")).casefold() in seen:
                continue
            return kind, item
        return None

    def _reference_kind(self, name: str, seen: frozenset[str]) -> str | None:
        resolved = self._resolve(name, seen)
        return "date" if resolved and str(resolved[1].get("datatype") or "").casefold() in DATE_TYPES else None

    def _reference(self, name: str, *, depth: int, seen: frozenset[str]) -> str:
        resolved = self._resolve(name, seen)
        if resolved is None:
            if any(str(item.get("calculation_id", "")).casefold() in seen for item in [self.calculations_by_id.get(name.casefold()) or {}]):
                raise Untranslatable(f"calculation {name} refers to itself")
            raise Untranslatable(f"unknown field {name}")
        kind, item = resolved
        if kind == "field":
            return self.field_column(item)
        calculation_id = str(item.get("calculation_id", "")).casefold()
        return "(" + self.translate(str(item.get("formula") or ""), depth=depth + 1, seen=seen | {calculation_id}) + ")"

    def _parameter(self, name: str) -> str:
        parameter = self.parameters.get(name.casefold())
        if parameter is None or parameter.get("default_value") in (None, ""):
            raise Untranslatable(f"parameter {name} has no default value")
        value = str(parameter["default_value"]).strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            return _string_literal(value)
        if value.startswith("#") and value.endswith("#"):
            return f"TO_DATE('{value.strip('#')}')"
        if re.fullmatch(r"-?\d+(\.\d+)?", value) or value.casefold() in {"true", "false"}:
            return value
        raise Untranslatable(f"parameter {name} default {value!r} is not supported")

    def _sequence(
        self, tokens: list[tuple[str, str]], position: int, *, depth: int, seen: frozenset[str], stop: set[str]
    ) -> tuple[str, int, str | None]:
        """Translate tokens until a top-level stop symbol (',' or ')').

        Returns the SQL, the stop position, and "date" when the whole sequence is a single date value.
        """
        parts: list[str] = []
        kinds: dict[int, str] = {}
        while position < len(tokens):
            kind, value = tokens[position]
            if kind == "SYMBOL" and value in stop:
                break
            if kind == "SYMBOL" and value in "{}":
                raise Untranslatable("LOD expressions are not supported yet")
            if kind == "FIELD_REF":
                is_qualified = (
                    position + 2 < len(tokens)
                    and tokens[position + 1] == ("SYMBOL", ".")
                    and tokens[position + 2][0] == "FIELD_REF"
                )
                if is_qualified:
                    if value.casefold() != "[parameters]":
                        raise Untranslatable(f"uses a field from another datasource ({value})")
                    parameter = self.parameters.get(tokens[position + 2][1].casefold()) or {}
                    if str(parameter.get("datatype") or "").casefold() in DATE_TYPES:
                        kinds[len(parts)] = "date"
                    parts.append(self._parameter(tokens[position + 2][1]))
                    position += 3
                    continue
                if self._reference_kind(value, seen):
                    kinds[len(parts)] = "date"
                parts.append(self._reference(value, depth=depth, seen=seen))
            elif kind == "STRING":
                parts.append(_string_literal(value))
            elif kind == "NUMBER":
                parts.append(value)
            elif kind == "WORD":
                upper = value.upper()
                is_call = position + 1 < len(tokens) and tokens[position + 1] == ("SYMBOL", "(")
                if is_call:
                    if upper in TABLE_CALCULATION_FUNCTIONS:
                        raise Untranslatable(f"table calculation {upper} is not supported")
                    if upper not in FUNCTIONS:
                        raise Untranslatable(f"function {upper} is not supported yet")
                    arguments, position = self._arguments(tokens, position + 2, depth=depth, seen=seen)
                    if upper in DATE_FUNCTIONS:
                        kinds[len(parts)] = "date"
                    parts.append(FUNCTIONS[upper](arguments))
                    continue
                if upper not in KEYWORDS:
                    raise Untranslatable(f"unknown word {value}")
                parts.append(KEYWORDS[upper])
            elif value == "(":
                inner, position, inner_kind = self._sequence(tokens, position + 1, depth=depth, seen=seen, stop={")"})
                if position >= len(tokens):
                    raise Untranslatable("unbalanced parentheses")
                if inner_kind:
                    kinds[len(parts)] = inner_kind
                parts.append(f"({inner})")
            elif value == "=" and position + 1 < len(tokens) and tokens[position + 1] == ("SYMBOL", "="):
                parts.append("=")
                position += 1
            elif value in {"!", "<", ">"} and position + 1 < len(tokens) and tokens[position + 1] == ("SYMBOL", "="):
                parts.append(value + "=")
                position += 1
            elif value == "<" and position + 1 < len(tokens) and tokens[position + 1] == ("SYMBOL", ">"):
                parts.append("<>")
                position += 1
            elif value in {"+", "-", "*", "/", "%", "=", "<", ">", ","}:
                parts.append(value)
            else:
                raise Untranslatable(f"unsupported symbol {value!r}")
            position += 1
        return self._date_differences(parts, kinds), position, ("date" if len(parts) == 1 and kinds.get(0) else None)

    @staticmethod
    def _date_differences(parts: list[str], kinds: dict[int, str]) -> str:
        """Tableau's date - date is a number of days; in Databricks it is an interval, so use DATEDIFF."""
        output: list[str] = []
        index = 0
        while index < len(parts):
            if (
                kinds.get(index) == "date"
                and index + 2 < len(parts)
                and parts[index + 1] == "-"
                and kinds.get(index + 2) == "date"
            ):
                output.append(f"CAST(DATEDIFF(DAY, {parts[index + 2]}, {parts[index]}) AS INT)")
                index += 3
                continue
            output.append(parts[index])
            index += 1
        return " ".join(output)

    def _arguments(
        self, tokens: list[tuple[str, str]], position: int, *, depth: int, seen: frozenset[str]
    ) -> tuple[list[str], int]:
        """Arguments of a call starting after '('; returns them and the position after ')'."""
        arguments: list[str] = []
        if position < len(tokens) and tokens[position] == ("SYMBOL", ")"):
            return arguments, position + 1
        while True:
            argument, position, _ = self._sequence(tokens, position, depth=depth, seen=seen, stop={",", ")"})
            if position >= len(tokens):
                raise Untranslatable("unbalanced parentheses")
            arguments.append(argument)
            if tokens[position][1] == ")":
                return arguments, position + 1
            position += 1

    def measure_reference(self, source_measure: dict[str, Any]) -> tuple[str, str]:
        """(reference SQL, aggregate family) for one parsed source measure, or Untranslatable."""
        expression = source_measure.get("expression") or {}
        aggregation = str(source_measure.get("aggregation") or "").upper()
        if expression.get("kind") == "field_aggregate":
            if aggregation == "ROW_COUNT":
                return "COUNT(*)", "ROW_COUNT"
            field = self.fields_by_id.get(str(expression.get("field_id") or "").casefold())
            if field is None:
                raise Untranslatable("field definition not found")
            column = self.field_column(field)
            templates = {
                "SUM": "SUM({c})", "AVG": "AVG({c})", "MIN": "MIN({c})", "MAX": "MAX({c})",
                "COUNT": "COUNT({c})", "COUNT_DISTINCT": "COUNT(DISTINCT {c})",
            }
            if aggregation not in templates:
                raise Untranslatable(f"aggregation {aggregation} is not supported")
            return templates[aggregation].format(c=column), aggregation
        semantic_type = str((expression.get("classification") or {}).get("semantic_type") or "")
        if semantic_type == "TABLE_CALCULATION":
            raise Untranslatable("table calculations depend on the worksheet layout")
        if semantic_type.startswith("LOD_"):
            raise Untranslatable("LOD expressions are not supported yet")
        translated = self.translate(str(expression.get("formula") or ""))
        # Decide on the translation, not the formula alone: [CP Profit] / [CP Sales] is aggregated
        # through the calculations it references.
        if SQL_AGGREGATE_PATTERN.search(translated):
            return translated, "CALCULATION"
        # Row-level calculations are totalled with SUM, Tableau's default for numeric measures.
        return f"SUM({translated})", "CALCULATION"
