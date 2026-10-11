"""Schema inference and quality table tests."""

from src.profiling import quality, schema


def test_column_group():
    assert schema.column_group("V12") == "V"
    assert schema.column_group("id_05") == "id"
    assert schema.column_group("card1") == "card"
    assert schema.column_group("ProductCD") == "other"


def test_cardinality_class():
    assert schema.cardinality_class(1) == "constant"
    assert schema.cardinality_class(10) == "low"
    assert schema.cardinality_class(500) == "medium"
    assert schema.cardinality_class(5000) == "high"


def test_infer_schema_types(frame):
    sch = schema.infer_schema(frame, time_col="TransactionDT").set_index("column")
    assert sch.loc["TransactionDT", "inferred_type"] == "datetime"
    assert sch.loc["TransactionID", "inferred_type"] == "id"
    assert sch.loc["M1", "inferred_type"] == "flag"
    assert sch.loc["ProductCD", "inferred_type"] == "categorical"
    assert sch.loc["card1", "inferred_type"] == "categorical"
    assert sch.loc["card1", "type_source"] == "dictionary"
    assert sch.loc["V1", "inferred_type"] == "numeric"
    assert sch.loc["const", "cardinality_class"] == "constant"
    assert set(sch.columns) >= {"inferred_type", "null_ratio", "cardinality_class"}
    assert len(sch) == frame.shape[1] + 1  # + index


def test_missing_and_quality(frame):
    sch = schema.infer_schema(frame, time_col="TransactionDT")
    miss = quality.missing_table(frame, sch).set_index("column")
    assert miss.loc["V1", "null_count"] == 80
    assert miss.loc["V1", "null_block"] == miss.loc["V2", "null_block"]
    groups = quality.group_missing(miss.reset_index())
    assert groups.set_index("group").loc["V", "n_columns"] == 3
    frame.loc[frame.index[0], "C1"] = -3
    checks = quality.quality_checks(frame, sch)
    assert (checks[checks["check"] == "constant_column"]["column"] == "const").any()
    assert (checks[checks["check"] == "negative_value"]["column"] == "C1").any()
    dup = checks[checks["check"] == "duplicate_rows"]["value"].iloc[0]
    assert dup == 0
