"""
Daily data generator: produces one day of new food-delivery data and uploads it to S3,
so the pipeline has fresh, realistic input every day.

For a logical date `ds` it writes four CSV files (same columns and order as the original
dataset, so the existing Snowflake COPY INTO statements load them unchanged):

    raw/orders/dt=<ds>/orders_<ds>.csv
    raw/order_items/dt=<ds>/order_items_<ds>.csv
    raw/reviews/dt=<ds>/reviews_<ds>.csv
    raw/restaurants/dt=<ds>/restaurants_<ds>.csv

Realistic situations built in on purpose:
  * late-arriving orders: ~2% of day D's orders only show up in day D+1's file
  * status changes: ~1% of day D-1's delivered orders are re-sent on day D as 'Refunded'
    (same order_id -> duplicate keys in RAW, handled later in staging)
  * dimension changes: ~50 restaurants per day change price or rating (feeds the SCD2 snapshot)
  * reviews arrive one day after the order
  * planted anomalies on some days (delivery delays or packaging complaints in one city)

Everything is deterministic for a given ds (seeded by the date, IDs derived from the date),
so re-running a day produces byte-identical files: the basis for idempotent backfills.

Usage:
    python generator/daily_generator.py --ds 2026-09-01 --no-upload   # write local files only
    python generator/daily_generator.py --ds 2026-09-01               # write and upload to S3
"""
import argparse
import csv
import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

REPO_ROOT = Path(__file__).resolve().parent.parent

# IDs are derived from the number of days since ID_EPOCH, so every day owns a fixed,
# non-overlapping ID range regardless of the order in which days are generated.
# The original dataset ends on 2026-06-30 with max ids: order 10M, order item ~23M, review 300K.
ID_EPOCH = date(2026, 7, 1)
ORDER_ID_BASE, ORDERS_PER_DAY_MAX = 20_000_000, 100_000
ORDER_ITEM_ID_BASE, ORDER_ITEMS_PER_DAY_MAX = 100_000_000, 1_000_000
REVIEW_ID_BASE, REVIEWS_PER_DAY_MAX = 1_000_000, 10_000

LATE_ARRIVAL_RATE = 0.02
STATUS_CHANGE_RATE = 0.01
REVIEW_RATE = 0.03
RESTAURANT_CHANGES_PER_DAY = 50

# Distributions measured on the original orders.csv / order_items.csv / reviews.csv
STATUSES = (["Delivered", "Cancelled", "Refunded"], [91.5, 6.0, 2.5])
PAYMENT_METHODS = (["UPI", "Card", "Wallet", "COD", "NetBanking"], [46, 20, 15, 14, 5])
ITEMS_PER_ORDER = ([1, 2, 3, 4, 5, 6], [30, 34, 20, 10, 4, 2])
QUANTITY_PER_LINE = ([1, 2, 3], [82, 14, 4])
DELIVERY_FEES = ([0, 15, 20, 25, 35, 49], [25, 20, 20, 15, 12, 8])
CUSTOMER_RATINGS = (["5.0", "4.0", "3.0", "2.0", "1.0"], [36, 45, 17, 1.7, 0.3])
REVIEW_RATINGS = ([5, 4, 3, 2, 1], [40, 25, 15, 10, 10])
HOUR_WEIGHTS = [829, 416, 199, 219, 178, 388, 1191, 3288, 4838, 5620, 6557, 8705,
                18343, 19326, 13016, 7250, 6674, 8950, 15359, 22364, 23930, 18193, 10057, 4110]

# The 30 review sentences of the original dataset, grouped by sentiment and topic.
NEGATIVE = {
    "food quality": ["Oily, stale and tasteless", "Quality has really dropped lately",
                     "The food was cold and bland"],
    "pricing": ["Overpriced and not worth it", "Portion was tiny for the price",
                "Far too expensive for what you get"],
    "delivery": ["Arrived way too late", "The rider got lost twice", "Delivery took over an hour"],
    "service": ["Got the wrong order entirely", "The delivery partner was rude"],
    "packaging": ["The packaging leaked everywhere", "Gravy spilled all over the bag"],
}
NEUTRAL = ["An average experience overall", "Fine, would maybe order again",
           "Decent but could be better", "It was okay, nothing special"]
POSITIVE = ["The delivery partner was polite and helpful", "Fresh, hot and full of flavor",
            "Arrived earlier than expected", "Great value for the price",
            "The food was absolutely delicious", "Super fast delivery",
            "Great eco-friendly packaging", "Neatly packed with no spills",
            "Totally worth every rupee", "One of the best meals i've ordered",
            "Delivered right on time", "Authentic taste, cooked perfectly",
            "Smooth, hassle-free experience"]

ANOMALY_CITIES = ["Bangalore", "Hyderabad", "Pune", "Chennai", "Mumbai", "Delhi"]

ORDER_COLUMNS = ["order_id", "order_timestamp", "order_date", "user_id", "r_id", "restaurant_city",
                 "cuisine", "items_count", "sales_qty", "subtotal", "discount", "delivery_fee", "gst",
                 "sales_amount", "currency", "payment_method", "order_status", "customer_rating",
                 "delivery_time_min"]
ORDER_ITEM_COLUMNS = ["order_item_id", "order_id", "r_id", "f_id", "price", "quantity", "line_amount"]
REVIEW_COLUMNS = ["review_id", "order_id", "user_id", "restaurant_id", "rating", "comment", "review_date"]
RESTAURANT_COLUMNS = ["", "id", "name", "city", "rating", "rating_count", "cost", "cuisine", "lic_no",
                      "link", "address", "menu"]


def day_index(ds):
    return (ds - ID_EPOCH).days


def pick(rng, choices):
    values, weights = choices
    return rng.choices(values, weights=weights, k=1)[0]


def city_of(raw_city):
    """'Indiranagar,Bangalore' -> 'Bangalore' (same rule as stg_orders / stg_restaurants)."""
    return raw_city.split(",")[-1].strip()


# --------------------------------------------------------------------------------------
# Reference data (static source CSVs in data/)
# --------------------------------------------------------------------------------------
class ReferenceData:
    def __init__(self, data_dir):
        self.menu = {}  # r_id -> [(f_id, price)]
        with open(data_dir / "menu.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    price = int(float(row["price"]))
                except (TypeError, ValueError):
                    continue
                if price > 0 and row["r_id"].isdigit():
                    self.menu.setdefault(int(row["r_id"]), []).append((row["f_id"], price))

        # menu.csv only covers part of the restaurants (none in Delhi, for example). Restaurants
        # without a menu get a fixed one drawn from the global pool of dishes, seeded by their id.
        self.dish_pool = sorted({dish for dishes in self.menu.values() for dish in dishes})

        self.restaurants = {}  # id -> original CSV row (dict)
        with open(data_dir / "restaurant.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["id"].isdigit():
                    self.restaurants[int(row["id"])] = row
        self.restaurant_ids = sorted(self.restaurants)

        # Fixed, mildly skewed popularity (seeded, independent of the day). The original orders
        # are spread roughly evenly over restaurants, so the skew is kept small.
        popularity = random.Random("restaurant-popularity")
        weights = [popularity.lognormvariate(0, 0.6) for _ in self.restaurant_ids]
        self.cum_weights = []
        total = 0.0
        for w in weights:
            total += w
            self.cum_weights.append(total)

        with open(data_dir / "users.csv", newline="", encoding="utf-8") as f:
            self.user_ids = sorted(int(r["user_id"]) for r in csv.DictReader(f) if r["user_id"].isdigit())

    def menu_for(self, r_id):
        if r_id not in self.menu:
            self.menu[r_id] = random.Random(f"menu-{r_id}").sample(self.dish_pool, 20)
        return self.menu[r_id]


# --------------------------------------------------------------------------------------
# Generation of one day (pure function of ds + reference data)
# --------------------------------------------------------------------------------------
def anomaly_for(ds):
    """Every 7th day carries one planted anomaly, alternating between two kinds."""
    idx = day_index(ds)
    if idx % 7 != 3:
        return None
    rng = random.Random(f"{ds}-anomaly")
    kind = "delivery_delay" if (idx // 7) % 2 == 0 else "packaging_complaints"
    return {"date": ds.isoformat(), "kind": kind, "city": rng.choice(ANOMALY_CITIES)}


def generate_orders(ds, ref, n_orders):
    """All orders whose event time is on ds, with their items. Returns (orders, items, late_ids)."""
    rng = random.Random(f"{ds}-orders")
    anomaly = anomaly_for(ds)
    if ds.weekday() >= 5:
        n_orders = int(n_orders * 1.15)
    assert n_orders < ORDERS_PER_DAY_MAX, "too many orders for the per-day ID range"

    idx = day_index(ds)
    restaurant_ids = rng.choices(ref.restaurant_ids, cum_weights=ref.cum_weights, k=n_orders)
    orders, items = [], []
    item_seq = 0
    for i, r_id in enumerate(restaurant_ids):
        restaurant = ref.restaurants[r_id]
        order_id = ORDER_ID_BASE + idx * ORDERS_PER_DAY_MAX + i
        ts = datetime.combine(ds, datetime.min.time()) + timedelta(
            hours=rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0],
            minutes=rng.randrange(60), seconds=rng.randrange(60))

        menu = ref.menu_for(r_id)
        n_lines = min(pick(rng, ITEMS_PER_ORDER), len(menu))
        subtotal = sales_qty = 0
        for f_id, price in rng.sample(menu, n_lines):
            qty = pick(rng, QUANTITY_PER_LINE)
            line = price * qty
            subtotal += line
            sales_qty += qty
            items.append([ORDER_ITEM_ID_BASE + idx * ORDER_ITEMS_PER_DAY_MAX + item_seq,
                          order_id, r_id, f_id, price, qty, line])
            item_seq += 1

        discount = round(subtotal * rng.uniform(0.10, 0.40)) if rng.random() < 0.35 else 0
        delivery_fee = pick(rng, DELIVERY_FEES)
        gst = round(subtotal * 0.05)
        status = pick(rng, STATUSES)

        rating, delivery_time = "", ""
        if status == "Delivered":
            minutes = min(87.0, max(8.0, rng.gauss(31.1, 10.8)))
            if anomaly and anomaly["kind"] == "delivery_delay" and city_of(restaurant["city"]) == anomaly["city"]:
                minutes = min(150.0, minutes * 1.4)
            delivery_time = f"{round(minutes):.1f}"
            if rng.random() < 0.70:
                rating = pick(rng, CUSTOMER_RATINGS)

        orders.append([order_id, ts.strftime("%Y-%m-%d %H:%M:%S"), ds.isoformat(), rng.choice(ref.user_ids),
                       r_id, restaurant["city"], restaurant["cuisine"], n_lines, sales_qty, subtotal,
                       discount, delivery_fee, gst, subtotal - discount + delivery_fee + gst, "INR",
                       pick(rng, PAYMENT_METHODS), status, rating, delivery_time])
    assert item_seq < ORDER_ITEMS_PER_DAY_MAX, "too many order items for the per-day ID range"

    late_rng = random.Random(f"{ds}-late")
    late_ids = {o[0] for o in orders if late_rng.random() < LATE_ARRIVAL_RATE}
    return orders, items, late_ids


def generate_status_changes(prev_ds, prev_orders, prev_late_ids):
    """Some delivered orders of the previous day are re-sent as Refunded (same order_id)."""
    rng = random.Random(f"{prev_ds}-status-changes")
    changes = []
    for o in prev_orders:
        if o[16] == "Delivered" and o[0] not in prev_late_ids and rng.random() < STATUS_CHANGE_RATE:
            changed = list(o)
            changed[16], changed[17], changed[18] = "Refunded", "", ""
            changes.append(changed)
    return changes


def generate_reviews(ds, prev_orders):
    """Reviews written on ds for orders delivered the previous day."""
    rng = random.Random(f"{ds}-reviews")
    prev_anomaly = anomaly_for(ds - timedelta(days=1))
    idx = day_index(ds)
    reviews = []
    for o in prev_orders:
        if o[16] != "Delivered" or rng.random() >= REVIEW_RATE:
            continue
        rating = pick(rng, REVIEW_RATINGS)
        n_sentences = 1 if rng.random() < 0.58 else 2
        packaging_issue = (prev_anomaly and prev_anomaly["kind"] == "packaging_complaints"
                           and city_of(o[5]) == prev_anomaly["city"] and rng.random() < 0.6)
        if packaging_issue:
            rating = rng.choice([1, 2])
            sentences = rng.sample(NEGATIVE["packaging"], n_sentences)
        elif rating <= 2:
            topic = rng.choice(sorted(NEGATIVE))
            sentences = rng.sample(NEGATIVE[topic], min(n_sentences, len(NEGATIVE[topic])))
        elif rating == 3:
            sentences = rng.sample(NEUTRAL, n_sentences)
        else:
            sentences = rng.sample(POSITIVE, n_sentences)
        assert len(reviews) < REVIEWS_PER_DAY_MAX, "too many reviews for the per-day ID range"
        reviews.append([REVIEW_ID_BASE + idx * REVIEWS_PER_DAY_MAX + len(reviews), o[0], o[3], o[4],
                        rating, " ".join(s + "." for s in sentences), ds.isoformat()])
    return reviews


def generate_restaurant_changes(ds, ref):
    """~50 restaurants change price or rating, relative to their original values."""
    rng = random.Random(f"{ds}-restaurants")
    rows = []
    for i, r_id in enumerate(sorted(rng.sample(ref.restaurant_ids, RESTAURANT_CHANGES_PER_DAY))):
        row = dict(ref.restaurants[r_id])
        if rng.random() < 0.5:
            digits = "".join(ch for ch in row["cost"] if ch.isdigit())
            base = int(digits) if digits else 300
            row["cost"] = f"₹ {max(50, round(base * rng.uniform(0.8, 1.3) / 10) * 10)}"
        else:
            try:
                base = float(row["rating"])
            except ValueError:
                base = 4.0
            row["rating"] = f"{min(5.0, max(1.0, base + rng.choice([-0.5, -0.3, -0.2, 0.2, 0.3]))):.1f}"
        rows.append([i] + [row[c] for c in RESTAURANT_COLUMNS[1:]])
    return rows


def build_day(ds, ref, n_orders, start_date):
    """Assemble the four files for ds, including carry-over from the previous day."""
    orders, items, late_ids = generate_orders(ds, ref, n_orders)
    file_orders = [o for o in orders if o[0] not in late_ids]
    file_items = [it for it in items if it[1] not in late_ids]
    file_reviews, status_changes = [], []

    prev_ds = ds - timedelta(days=1)
    if ds > start_date:  # the previous day was generated too, so carry its late data over
        prev_orders, prev_items, prev_late_ids = generate_orders(prev_ds, ref, n_orders)
        file_orders += [o for o in prev_orders if o[0] in prev_late_ids]
        file_items += [it for it in prev_items if it[1] in prev_late_ids]
        status_changes = generate_status_changes(prev_ds, prev_orders, prev_late_ids)
        file_orders += status_changes
        file_reviews = generate_reviews(ds, prev_orders)

    files = {
        "orders": (ORDER_COLUMNS, file_orders),
        "order_items": (ORDER_ITEM_COLUMNS, file_items),
        "reviews": (REVIEW_COLUMNS, file_reviews),
        "restaurants": (RESTAURANT_COLUMNS, generate_restaurant_changes(ds, ref)),
    }
    summary = {
        "ds": ds.isoformat(),
        "orders_on_time": len(orders) - len(late_ids),
        "orders_late_from_previous_day": len(file_orders) - (len(orders) - len(late_ids)) - len(status_changes),
        "orders_held_back_until_next_day": len(late_ids),
        "status_changes": len(status_changes),
        "order_items": len(file_items),
        "reviews": len(file_reviews),
        "restaurant_changes": RESTAURANT_CHANGES_PER_DAY,
        "anomaly": anomaly_for(ds),
    }
    return files, summary


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------
def write_files(ds, files, out_dir):
    paths = {}
    for table, (columns, rows) in files.items():
        path = out_dir / table / f"dt={ds}" / f"{table}_{ds}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(columns)
            writer.writerows(rows)
        paths[table] = path
    return paths


def upload_files(ds, paths, bucket, prefix):
    import boto3  # only needed when uploading

    s3 = boto3.client("s3")
    for table, path in paths.items():
        key = f"{prefix}/{table}/dt={ds}/{path.name}"
        s3.upload_file(str(path), bucket, key)
        print(f"  uploaded s3://{bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description="Generate one day of food-delivery data.")
    parser.add_argument("--ds", required=True, help="logical date, YYYY-MM-DD")
    parser.add_argument("--orders", type=int, default=int(os.environ.get("GENERATOR_ORDERS_PER_DAY", "25000")))
    parser.add_argument("--start-date", default=os.environ.get("GENERATOR_START_DATE", "2026-09-01"),
                        help="first generated day; no carry-over (late orders, refunds, reviews) before it")
    parser.add_argument("--data-dir", default=str(REPO_ROOT / "data"))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "generator" / "output"))
    parser.add_argument("--no-upload", action="store_true", help="only write local files")
    args = parser.parse_args()

    ds = date.fromisoformat(args.ds)
    start_date = date.fromisoformat(args.start_date)
    if ds < ID_EPOCH or ds < start_date:
        raise SystemExit(f"--ds must be on or after {max(ID_EPOCH, start_date)}")

    print(f"Loading reference data from {args.data_dir} ...")
    ref = ReferenceData(Path(args.data_dir))
    files, summary = build_day(ds, ref, args.orders, start_date)
    paths = write_files(ds, files, Path(args.out_dir))
    print(json.dumps(summary, indent=2))

    if args.no_upload:
        print(f"Files written under {args.out_dir} (upload skipped).")
        return
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise SystemExit("S3_BUCKET is not set (see generator/.env.example)")
    upload_files(ds, paths, bucket, os.environ.get("S3_PREFIX", "raw"))


if __name__ == "__main__":
    main()
