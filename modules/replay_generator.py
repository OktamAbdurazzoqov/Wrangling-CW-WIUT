from __future__ import annotations

import json
import textwrap
from typing import Any


def _repr(value: Any) -> str:
    return repr(value)


def _normalise_action(action: str) -> str:
    return action.lower().strip().replace(" ", "_").replace("-", "_")


def _action_to_code(action: str, details: dict) -> list[str]:
    name = _normalise_action(action)

    if name in (
        "missing_values",
        "fill_missing",
        "fill_na",
        "fillna",
        "impute",
        "handle_missing",
        "handle_missing_values",
        "fill_missing_values",
        "missing_value_handling",
    ):
        inner = (details.get("action") or details.get("method") or details.get("strategy") or "").lower()
        cols = details.get("columns") or ([details["column"]] if "column" in details else [])
        value = details.get("value") or details.get("custom_value")
        lines = []
        if "drop rows above threshold" in inner:
            threshold = details.get("threshold", 50)
            lines.append(f"_pct = df[{_repr(cols)}].isna().mean(axis=1) * 100")
            lines.append(f"df = df[_pct <= {threshold}].copy()")
        elif "drop columns above threshold" in inner:
            threshold = details.get("threshold", 50)
            lines.append(f"_drop = [c for c in {_repr(cols)} if df[c].isna().mean() * 100 > {threshold}]")
            lines.append("df = df.drop(columns=_drop)")
        elif "drop rows" in inner or inner == "drop":
            lines.append(f"df = df.dropna(subset={_repr(cols)})")
        else:
            for col in cols:
                target = f"df[{_repr(col)}]"
                if "median" in inner:
                    lines.append(f"{target} = {target}.fillna({target}.median())")
                elif "mean" in inner:
                    lines.append(f"{target} = {target}.fillna({target}.mean())")
                elif "mode" in inner or "most frequent" in inner or "frequent" in inner:
                    lines.append(f"{target} = {target}.fillna({target}.mode().iloc[0] if not {target}.mode().empty else {target})")
                elif "forward fill" in inner or "ffill" in inner:
                    lines.append(f"{target} = {target}.ffill()")
                elif "backward fill" in inner or "bfill" in inner:
                    lines.append(f"{target} = {target}.bfill()")
                elif "custom" in inner or value is not None:
                    lines.append(f"{target} = {target}.fillna({_repr(value)})")
                else:
                    lines.append(f"print('Unrecognized missing-value action for {col}')")
        return lines or ["print('No missing-value columns were recorded')"]

    if name in ("drop_missing", "drop_na", "dropna", "remove_missing", "drop_rows_with_missing"):
        col = details.get("column")
        cols = details.get("columns")
        how = _repr(details.get("how", "any"))
        threshold = details.get("thresh")
        if col:
            return [f"df = df.dropna(subset={_repr([col])})"]
        if cols:
            return [f"df = df.dropna(subset={_repr(cols)}, how={how})"]
        if threshold:
            return [f"df = df.dropna(thresh={threshold})"]
        return [f"df = df.dropna(how={how})"]

    if name in ("duplicate_handling", "drop_duplicates", "remove_duplicates", "deduplicate", "duplicate_removal", "duplicates"):
        inner = (details.get("action") or "").lower()
        subset = details.get("subset") or details.get("columns")
        keep = False if "all" in inner or "no copies" in inner else "last" if "last" in inner else "first"
        if subset:
            return [f"df = df.drop_duplicates(subset={_repr(subset)}, keep={_repr(keep)})"]
        return [f"df = df.drop_duplicates(keep={_repr(keep)})"]

    if name in ("data_type_conversion", "change_dtype", "convert_dtype", "cast", "astype", "type_conversion", "change_type", "convert_type", "data_types"):
        col = details.get("column")
        cols = details.get("columns")
        dtype_raw = (details.get("type") or details.get("dtype", "str")).lower().strip()
        numeric_labels = {"to numeric", "to_numeric", "numeric", "float", "float64", "int", "int64", "integer", "to integer", "to_integer"}
        integer_labels = {"int", "int64", "integer", "to integer", "to_integer"}
        datetime_labels = {"to datetime", "to_datetime", "datetime", "date"}
        string_labels = {"string", "str", "to string", "to_string", "text", "object"}
        bool_labels = {"bool", "boolean", "to boolean", "to_boolean"}
        categorical_labels = {"category", "categorical", "to categorical", "to_categorical"}
        targets = cols if cols else ([col] if col else [])
        if not targets:
            return ["print('No columns were recorded for data type conversion')"]
        lines = []
        if dtype_raw in numeric_labels:
            for target in targets:
                lines.append(f"df[{_repr(target)}] = pd.to_numeric(df[{_repr(target)}], errors='coerce')")
            if dtype_raw in integer_labels:
                for target in targets:
                    lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype('Int64')")
        elif dtype_raw in datetime_labels:
            fmt = details.get("format")
            for target in targets:
                args = f"df[{_repr(target)}], errors='coerce'"
                if fmt:
                    args += f", format={_repr(fmt)}"
                lines.append(f"df[{_repr(target)}] = pd.to_datetime({args})")
        elif dtype_raw in string_labels:
            for target in targets:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype(str)")
        elif dtype_raw in bool_labels:
            for target in targets:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype(bool)")
        elif dtype_raw in categorical_labels:
            for target in targets:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype('category')")
        else:
            for target in targets:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype({_repr(dtype_raw)})")
        return lines

    if name in ("outlier_handling", "remove_outliers", "drop_outliers", "outlier_removal", "outliers", "handle_outliers"):
        inner = (details.get("action") or "").lower()
        cols = details.get("columns") or ([details["column"]] if "column" in details else [])
        lower = details.get("lower_percentile", 0.05)
        upper = details.get("upper_percentile", 0.95)
        lines = []
        if "cap" in inner or "winsoriz" in inner:
            for col in cols:
                lines.extend(
                    [
                        f"_lo = df[{_repr(col)}].quantile({lower})",
                        f"_hi = df[{_repr(col)}].quantile({upper})",
                        f"df[{_repr(col)}] = df[{_repr(col)}].clip(_lo, _hi)",
                    ]
                )
        elif "remove" in inner or "drop" in inner:
            for col in cols:
                lines.extend(
                    [
                        f"_lo = df[{_repr(col)}].quantile({lower})",
                        f"_hi = df[{_repr(col)}].quantile({upper})",
                        f"df = df[(df[{_repr(col)}] >= _lo) & (df[{_repr(col)}] <= _hi)]",
                    ]
                )
        else:
            lines.append("print('Outlier step was preview-only and does not change the dataframe')")
        return lines or ["print('No outlier columns were recorded')"]

    if name in (
        "scaling",
        "scale",
        "normalise",
        "normalize",
        "standardise",
        "standardize",
        "normalisation",
        "normalization",
        "standardisation",
        "standardization",
        "min_max_scale",
        "zscore_scale",
        "feature_scaling",
    ):
        cols = details.get("columns") or ([details["column"]] if "column" in details else [])
        method = (details.get("method") or "").lower()
        lines = []
        if "z-score" in method or "zscore" in method or "standard" in method or "mean=0" in method:
            for col in cols:
                lines.extend(
                    [
                        f"_mean = df[{_repr(col)}].mean()",
                        f"_std = df[{_repr(col)}].std()",
                        f"df[{_repr(col)}] = (df[{_repr(col)}] - _mean) / _std",
                    ]
                )
        elif ("min" in method and "max" in method) or "minmax" in method:
            for col in cols:
                lines.extend(
                    [
                        f"_min = df[{_repr(col)}].min()",
                        f"_max = df[{_repr(col)}].max()",
                        f"df[{_repr(col)}] = (df[{_repr(col)}] - _min) / (_max - _min)",
                    ]
                )
        elif "robust" in method:
            for col in cols:
                lines.extend(
                    [
                        f"_med = df[{_repr(col)}].median()",
                        f"_iqr = df[{_repr(col)}].quantile(0.75) - df[{_repr(col)}].quantile(0.25)",
                        f"df[{_repr(col)}] = (df[{_repr(col)}] - _med) / _iqr",
                    ]
                )
        elif "log" in method:
            lines.append("import numpy as np")
            for col in cols:
                lines.append(f"df[{_repr(col)}] = np.log1p(df[{_repr(col)}])")
        else:
            for col in cols:
                lines.extend(
                    [
                        f"_mean = df[{_repr(col)}].mean()",
                        f"_std = df[{_repr(col)}].std()",
                        f"df[{_repr(col)}] = (df[{_repr(col)}] - _mean) / _std",
                    ]
                )
        return lines

    if name in ("categorical_cleaning", "categorical_clean"):
        cols = details.get("columns", [])
        if not cols:
            return ["print('No categorical columns were recorded')"]
        lines = []
        for col in cols:
            if details.get("trim"):
                lines.append(
                    f"df[{_repr(col)}] = df[{_repr(col)}].where(df[{_repr(col)}].isna(), df[{_repr(col)}].astype(str).str.strip())"
                )
            if details.get("lower"):
                lines.append(
                    f"df[{_repr(col)}] = df[{_repr(col)}].where(df[{_repr(col)}].isna(), df[{_repr(col)}].astype(str).str.lower())"
                )
            if details.get("title"):
                lines.append(
                    f"df[{_repr(col)}] = df[{_repr(col)}].where(df[{_repr(col)}].isna(), df[{_repr(col)}].astype(str).str.title())"
                )
            mapping = details.get("mapping")
            if mapping:
                alias = col.replace(" ", "_")
                lines.append(f"_map_{alias} = {_repr(mapping)}")
                if details.get("set_unmatched"):
                    other = details.get("other_value", "Other")
                    lines.append(f"df[{_repr(col)}] = df[{_repr(col)}].astype(str).map(_map_{alias}).fillna({_repr(other)})")
                else:
                    lines.append(f"_mapped = df[{_repr(col)}].astype(str).map(_map_{alias})")
                    lines.append(f"df[{_repr(col)}] = _mapped.where(_mapped.notna(), df[{_repr(col)}])")
            if details.get("rare_grouping"):
                threshold = details.get("rare_threshold", 0.05)
                label = details.get("rare_label", "Other")
                lines.extend(
                    [
                        f"_freq = df[{_repr(col)}].value_counts(normalize=True)",
                        f"_rare = _freq[_freq < {threshold}].index",
                        f"df[{_repr(col)}] = df[{_repr(col)}].where(~df[{_repr(col)}].isin(_rare), {_repr(label)})",
                    ]
                )
        if details.get("one_hot"):
            encoded_cols = cols[:]
            if details.get("keep_original_ohe"):
                for col in encoded_cols:
                    lines.append(f"_{col.replace(' ', '_')}_orig = df[{_repr(col)}].copy()")
            lines.append(f"df = pd.get_dummies(df, columns={_repr(encoded_cols)})")
            if details.get("keep_original_ohe"):
                for col in encoded_cols:
                    lines.append(f"df[{_repr(col + '_original')}] = _{col.replace(' ', '_')}_orig")
        return lines or [f"print('No categorical changes were recorded for {cols}')"]

    if name in ("drop_columns", "drop_column", "remove_column", "remove_columns", "delete_column", "delete_columns"):
        cols = details.get("columns") or ([details["column"]] if "column" in details else [])
        return [f"df = df.drop(columns=[c for c in {_repr(cols)} if c in df.columns])"]

    if name in ("rename_column", "rename_columns", "rename"):
        mapping = details.get("mapping") or details.get("rename_map", {})
        if not mapping and "old_name" in details and "new_name" in details:
            mapping = {details["old_name"]: details["new_name"]}
        return [
            f"_rename = {{k: v for k, v in {_repr(mapping)}.items() if k in df.columns}}",
            "df = df.rename(columns=_rename)",
        ]

    if name in ("create_column", "add_column", "new_column"):
        import re

        col = details.get("new_column") or details.get("column", "new_col")
        formula = details.get("formula") or details.get("expression") or details.get("value", "None")
        py_expr = re.sub(r'\[([^\]]+)\]', r'df["\1"]', str(formula))
        return [f"df[{_repr(col)}] = {py_expr}"]

    if name == "split_column":
        col = details.get("column", "col")
        delimiter = details.get("delimiter", "/")
        return [
            f"_split = df[{_repr(col)}].astype(str).str.split({_repr(delimiter)}, n=1, expand=True)",
            f"df[{_repr(col)}_part1] = _split[0].str.strip()",
            f"df[{_repr(col)}_part2] = _split[1].str.strip() if _split.shape[1] > 1 else ''",
        ]

    if name in ("binning_(equal_width)", "binning_(quantile)", "binning"):
        col = details.get("column", "col")
        bins = details.get("bins", 5)
        label = details.get("new_column", f"{col}_bin")
        if "quantile" in name:
            return [f"df[{_repr(label)}] = pd.qcut(df[{_repr(col)}], q={bins}, duplicates='drop').astype(str)"]
        return [f"df[{_repr(label)}] = pd.cut(df[{_repr(col)}], bins={bins}).astype(str)"]

    if name in ("reorder_columns", "reorder"):
        cols = details.get("columns", [])
        return [f"df = df[{_repr(cols)}]"]

    if name in ("strip_whitespace", "strip", "trim_whitespace", "trim", "whitespace"):
        col = details.get("column")
        cols = details.get("columns")
        if col:
            return [f"df[{_repr(col)}] = df[{_repr(col)}].str.strip()"]
        if cols:
            return [f"df[{_repr(target)}] = df[{_repr(target)}].str.strip()" for target in cols]
        return [
            "obj_cols = df.select_dtypes(include='object').columns",
            "df[obj_cols] = df[obj_cols].apply(lambda s: s.str.strip())",
        ]

    if name in ("to_lowercase", "lowercase", "lower", "to_lower"):
        col = details.get("column")
        cols = details.get("columns") or ([col] if col else [])
        return [f"df[{_repr(target)}] = df[{_repr(target)}].str.lower()" for target in cols]

    if name in ("to_uppercase", "uppercase", "upper", "to_upper"):
        col = details.get("column")
        cols = details.get("columns") or ([col] if col else [])
        return [f"df[{_repr(target)}] = df[{_repr(target)}].str.upper()" for target in cols]

    if name in ("replace_value", "replace", "find_replace", "value_replacement", "replace_values"):
        col = details.get("column")
        to_find = details.get("find") or details.get("old_value")
        replace_value = details.get("replace") or details.get("new_value")
        regex = details.get("regex", False)
        if col:
            return [f"df[{_repr(col)}] = df[{_repr(col)}].replace({_repr(to_find)}, {_repr(replace_value)}, regex={regex})"]
        return [f"df = df.replace({_repr(to_find)}, {_repr(replace_value)}, regex={regex})"]

    if name in ("filter_rows", "filter", "keep_rows", "row_filter"):
        condition = details.get("condition") or details.get("query")
        if condition:
            return [f"df = df.query({_repr(condition)})"]
        col = details.get("column")
        operator = details.get("operator", "==")
        value = details.get("value")
        if col:
            if operator == "in":
                return [f"df = df[df[{_repr(col)}].isin({_repr(value)})]"]
            if operator == "not in":
                return [f"df = df[~df[{_repr(col)}].isin({_repr(value)})]"]
            if operator in ("contains", "str_contains"):
                return [f"df = df[df[{_repr(col)}].str.contains({_repr(value)}, na=False)]"]
            return [f"df = df[df[{_repr(col)}] {operator} {_repr(value)}]"]

    if name in ("sort", "sort_rows", "sort_by", "sort_values"):
        by = details.get("by") or details.get("columns") or details.get("column")
        ascending = details.get("ascending", True)
        na_position = _repr(details.get("na_position", "last"))
        return [f"df = df.sort_values(by={_repr(by)}, ascending={ascending}, na_position={na_position}).reset_index(drop=True)"]

    if name in ("one_hot_encode", "one_hot_encoding", "get_dummies", "encode", "encoding"):
        col = details.get("column")
        cols = details.get("columns") or ([col] if col else [])
        return [f"df = pd.get_dummies(df, columns={_repr(cols)})"]

    if name in ("label_encode", "label_encoding", "ordinal_encode", "ordinal_encoding"):
        col = details.get("column")
        cols = details.get("columns") or ([col] if col else [])
        mapping = details.get("mapping")
        lines = []
        for target in cols:
            if mapping:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].map({_repr(mapping)})")
            else:
                lines.append(f"df[{_repr(target)}] = df[{_repr(target)}].astype('category').cat.codes")
        return lines

    if name == "reset_index":
        return ["df = df.reset_index(drop=True)"]

    if name == "set_index":
        col = details.get("column")
        return [f"df = df.set_index({_repr(col)})"]

    if name in ("groupby", "group_by", "aggregate", "aggregation"):
        by = details.get("by") or details.get("group_by")
        agg = details.get("agg") or details.get("aggregation", {})
        return [f"df = df.groupby({_repr(by)}).agg({_repr(agg)}).reset_index()"]

    if name in ("clip", "clip_values"):
        col = details.get("column")
        low = details.get("lower", details.get("min"))
        high = details.get("upper", details.get("max"))
        if col:
            return [f"df[{_repr(col)}] = df[{_repr(col)}].clip(lower={low}, upper={high})"]

    return [
        f"print('Action not mapped: {action}')",
        f"print({_repr(json.dumps(details, default=str))})",
    ]


def generate_replay_script(logs: list[dict], source_file: str = "your_file.csv") -> str:
    header = textwrap.dedent(
        f"""\
        import pandas as pd

        df = pd.read_csv({_repr(source_file)})
        print(f"Loaded {{len(df):,}} rows x {{len(df.columns)}} columns")
        """
    )
    body_lines: list[str] = []
    for entry in logs:
        action = entry.get("action", "unknown")
        details = entry.get("details") or {}
        body_lines.append(f"print('Applying: {action}')")
        body_lines.extend(_action_to_code(action, details))
        body_lines.append("")
    footer = textwrap.dedent(
        """\
        print(f"Final shape: {df.shape}")
        df.to_csv("cleaned_dataset.csv", index=False)
        print("Saved -> cleaned_dataset.csv")
        """
    )
    return header + "\n".join(body_lines) + "\n" + footer
