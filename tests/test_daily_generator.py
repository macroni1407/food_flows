"""
Tests for generator/daily_generator.py, run on the small fixture data in tests/fixtures/data
(the real data/ folder is not in the repository).

They pin down the properties the rest of the pipeline relies on: files that load into the RAW
tables, consistent amounts, non-overlapping IDs, and byte-identical output when a day is re-run.
"""
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
import daily_generator as g  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "data"
START = date(2026, 9, 1)          # a Tuesday
ORDERS = 2000                     # small day to keep the tests fast


@pytest.fixture(scope="module")
def ref():
    return g.ReferenceData(FIXTURES)


def day(ref, ds, start=START):
    files, summary = g.build_day(ds, ref, ORDERS, start)
    return {table: rows for table, (_, rows) in files.items()}, summary


def test_same_day_produces_byte_identical_files(ref, tmp_path):
    ds = START + timedelta(days=1)
    first, _ = g.build_day(ds, ref, ORDERS, START)
    second, _ = g.build_day(ds, ref, ORDERS, START)
    paths_a = g.write_files(ds, first, tmp_path / "a")
    paths_b = g.write_files(ds, second, tmp_path / "b")
    for table in paths_a:
        assert paths_a[table].read_bytes() == paths_b[table].read_bytes(), table


def test_rows_match_raw_table_columns(ref):
    files, _ = g.build_day(START + timedelta(days=1), ref, ORDERS, START)
    expected = {"orders": 19, "order_items": 7, "reviews": 7, "restaurants": 12}
    for table, (columns, rows) in files.items():
        assert len(columns) == expected[table], table
        assert rows, f"{table} is empty"
        assert all(len(row) == expected[table] for row in rows), table


def test_amounts_are_consistent(ref):
    files, _ = day(ref, START)
    line_totals = Counter()
    for item in files["order_items"]:
        _, order_id, _, _, price, quantity, line_amount = item
        assert line_amount == price * quantity
        line_totals[order_id] += line_amount
    for o in files["orders"]:
        subtotal, discount, delivery_fee, gst, sales_amount = o[9], o[10], o[11], o[12], o[13]
        assert gst == round(subtotal * 0.05)
        assert sales_amount == subtotal - discount + delivery_fee + gst
        assert subtotal == line_totals[o[0]]


def test_ids_never_overlap_between_days_or_with_original_data(ref):
    a, _ = day(ref, START)
    b, _ = day(ref, START + timedelta(days=1))
    own_b = {o[0] for o in b["orders"] if o[2] == (START + timedelta(days=1)).isoformat()}
    ids_a = {o[0] for o in a["orders"]}
    assert ids_a.isdisjoint(own_b)
    assert min(ids_a) > 10_000_000  # original dataset ends at order_id 10,000,000
    items_a = {i[0] for i in a["order_items"]}
    items_b = {i[0] for i in b["order_items"]}
    assert items_a.isdisjoint(items_b)
    assert min(items_a) > 23_000_000


def test_late_orders_arrive_in_the_next_days_file(ref):
    d1, d2 = START + timedelta(days=1), START + timedelta(days=2)
    _, _, late_ids = g.generate_orders(d1, ref, ORDERS)
    assert late_ids, "expected some late-arriving orders"
    file_d1, _ = day(ref, d1)
    file_d2, _ = day(ref, d2)
    assert late_ids.isdisjoint({o[0] for o in file_d1["orders"]})
    arrived = {o[0] for o in file_d2["orders"] if o[2] == d1.isoformat() and o[16] != "Refunded"}
    assert late_ids <= arrived
    assert late_ids <= {i[1] for i in file_d2["order_items"]}


def test_status_changes_resend_delivered_orders_as_refunded(ref):
    d1, d2 = START + timedelta(days=1), START + timedelta(days=2)
    file_d1, _ = day(ref, d1)
    file_d2, summary = day(ref, d2)
    delivered_d1 = {o[0] for o in file_d1["orders"] if o[16] == "Delivered"}
    resent = [o for o in file_d2["orders"] if o[0] in {x[0] for x in file_d1["orders"]}]
    assert len(resent) == summary["status_changes"] > 0
    for o in resent:
        assert o[0] in delivered_d1
        assert o[16] == "Refunded" and o[17] == "" and o[18] == ""


def test_first_day_has_no_carry_over(ref):
    files, summary = day(ref, START)
    assert summary["orders_late_from_previous_day"] == 0
    assert summary["status_changes"] == 0
    assert files["reviews"] == []
    assert all(o[2] == START.isoformat() for o in files["orders"])


def test_reviews_are_written_the_next_day_for_delivered_orders(ref):
    d1, d2 = START + timedelta(days=1), START + timedelta(days=2)
    orders_d1, _, _ = g.generate_orders(d1, ref, ORDERS)
    delivered = {o[0] for o in orders_d1 if o[16] == "Delivered"}
    files, _ = day(ref, d2)
    assert files["reviews"]
    for r in files["reviews"]:
        assert r[1] in delivered
        assert r[6] == d2.isoformat()
        assert 1 <= r[4] <= 5 and r[5].endswith(".")


def test_restaurant_changes_keep_the_original_columns(ref):
    files, _ = day(ref, START)
    rows = files["restaurants"]
    assert len(rows) == g.RESTAURANT_CHANGES_PER_DAY
    for row in rows:
        original = ref.restaurants[int(row[1])]
        assert row[2] == original["name"] and row[3] == original["city"]
        assert row[6].startswith("₹ ")


def test_weekends_have_more_orders(ref):
    saturday = date(2026, 9, 5)
    weekday, _, _ = g.generate_orders(START, ref, ORDERS)
    weekend, _, _ = g.generate_orders(saturday, ref, ORDERS)
    assert len(weekend) == int(ORDERS * 1.15) > len(weekday) == ORDERS


def test_anomalies_every_seventh_day_alternating_kinds():
    days = [g.ID_EPOCH + timedelta(days=i) for i in range(70)]
    anomalies = [g.anomaly_for(d) for d in days]
    hits = [(d, a) for d, a in zip(days, anomalies) if a]
    assert len(hits) == 10
    assert all(g.day_index(d) % 7 == 3 for d, _ in hits)
    kinds = [a["kind"] for _, a in hits]
    assert kinds[0::2] == ["delivery_delay"] * 5 and kinds[1::2] == ["packaging_complaints"] * 5


def test_cli_rejects_dates_before_the_start_date(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["daily_generator.py", "--ds", "2026-08-31", "--start-date", "2026-09-01",
                                      "--no-upload"])
    with pytest.raises(SystemExit):
        g.main()


def test_cli_writes_partitioned_files_without_uploading(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["daily_generator.py", "--ds", "2026-09-02", "--start-date", "2026-09-01",
                                      "--orders", "300", "--data-dir", str(FIXTURES), "--out-dir", str(tmp_path),
                                      "--no-upload"])
    g.main()
    for table in ("orders", "order_items", "reviews", "restaurants"):
        assert (tmp_path / table / "dt=2026-09-02" / f"{table}_2026-09-02.csv").exists()
