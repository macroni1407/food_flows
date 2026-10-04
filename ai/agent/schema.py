"""
Schema description for the text-to-SQL prompt, generated from dbt artifacts so it never drifts
from the real models: manifest.json (models, descriptions) and catalog.json (column types, from
`dbt docs generate`; optional).
"""
import json

from . import settings

HIDDEN_COLUMNS = {"email"}   # PII (masked anyway) and not useful for questions

# Join keys between the marts
RELATIONSHIPS = """\
- FCT_ORDERS.RESTAURANT_ID = DIM_RESTAURANTS.RESTAURANT_ID
- FCT_ORDERS.CUSTOMER_ID = DIM_CUSTOMER.CUSTOMER_ID
- FCT_ORDERS.ORDER_DATE = DIM_DATE.DATE_DAY
- FCT_ORDER_ITEMS.ORDER_ID = FCT_ORDERS.ORDER_ID
- FCT_ORDER_ITEMS.F_ID = DIM_FOOD.F_ID
- FCT_ORDERS_POINT_IN_TIME.ORDER_ID = FCT_ORDERS.ORDER_ID
- DIM_RESTAURANTS_HISTORY.RESTAURANT_ID = DIM_RESTAURANTS.RESTAURANT_ID (one row per version)"""


class SchemaUnavailable(RuntimeError):
    pass


def load_marts(target_dir=None):
    """Return [{name, description, columns: [(name, type, description)]}] for every mart model."""
    target = target_dir or settings.DBT_TARGET_DIR
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        raise SchemaUnavailable(f"{manifest_path} not found: run `dbt parse` or `dbt build` first")
    manifest = json.loads(manifest_path.read_text())

    catalog_nodes = {}
    catalog_path = target / "catalog.json"
    if catalog_path.exists():
        catalog_nodes = json.loads(catalog_path.read_text()).get("nodes", {})

    marts = []
    for unique_id, node in manifest["nodes"].items():
        if node.get("resource_type") != "model" or len(node.get("fqn", [])) < 2 or node["fqn"][1] != "marts":
            continue
        types = {
            name.lower(): column.get("type", "")
            for name, column in catalog_nodes.get(unique_id, {}).get("columns", {}).items()
        }
        columns = []
        seen = set()
        for name, column in node.get("columns", {}).items():
            columns.append((name.lower(), types.get(name.lower(), ""), column.get("description", "")))
            seen.add(name.lower())
        for name, type_ in types.items():          # columns present in the warehouse but undocumented
            if name not in seen:
                columns.append((name, type_, ""))
        columns = [c for c in columns if not c[0].startswith("_") and c[0] not in HIDDEN_COLUMNS]
        marts.append({"name": node["name"].upper(), "description": node.get("description", ""), "columns": columns})
    if not marts:
        raise SchemaUnavailable("no models under models/marts found in manifest.json")
    return sorted(marts, key=lambda m: m["name"])


def allowed_tables(marts):
    return {m["name"] for m in marts}


def describe(marts, categorical_values=None):
    """Plain-text schema for the prompt."""
    lines = []
    for mart in marts:
        lines.append(f"{mart['name']}: {mart['description']}")
        for name, type_, description in mart["columns"]:
            parts = [f"  - {name}"]
            if type_:
                parts.append(f" ({type_})")
            if description:
                parts.append(f": {description}")
            lines.append("".join(parts))
        lines.append("")
    lines.append("Join keys:")
    lines.append(RELATIONSHIPS)
    if categorical_values:
        lines.append("")
        lines.append("Valid values (use exactly, case-sensitive):")
        for key, values in sorted(categorical_values.items()):
            lines.append(f"- {key}: " + ", ".join(f"'{v}'" for v in values))
    return "\n".join(lines)
