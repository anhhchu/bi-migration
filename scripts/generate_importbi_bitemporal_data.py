import argparse
import json
from pathlib import Path

from databricks.connect import DatabricksSession
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


N_CUSTOMERS = 5_000
N_PRODUCTS = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create repeatable Superstore migration test data in Unity Catalog."
    )
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--order-lines", type=int, default=100_000)
    parser.add_argument(
        "--metadata-output",
        help="Optional local JSON path for pipeline target metadata.",
    )
    return parser.parse_args()


args = parse_args()
CATALOG = args.catalog
SCHEMA = args.schema
N_ORDER_LINES = args.order_lines


def write_table(dataframe: DataFrame, name: str) -> None:
    dataframe.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        f"{CATALOG}.{SCHEMA}.{name}"
    )


spark = DatabricksSession.builder.profile(args.profile).serverless(True).getOrCreate()
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

customers = spark.range(N_CUSTOMERS, numPartitions=8).select(
    F.format_string("C%05d", F.col("id")).alias("customer_key"),
    F.concat(F.lit("Customer "), F.format_string("%05d", F.col("id"))).alias(
        "customer_name"
    ),
    F.when(F.col("id") % 20 == 0, "Enterprise")
    .when(F.col("id") % 5 == 0, "Corporate")
    .otherwise("Consumer")
    .alias("segment"),
    F.element_at(
        F.array(F.lit("West"), F.lit("East"), F.lit("Central"), F.lit("South")),
        (F.col("id") % 4 + 1).cast("int"),
    ).alias("region"),
    F.lit("United States").alias("country"),
    F.element_at(
        F.array(F.lit("CA"), F.lit("NY"), F.lit("TX"), F.lit("IL")),
        (F.col("id") % 4 + 1).cast("int"),
    ).alias("state"),
    F.element_at(
        F.array(F.lit("San Francisco"), F.lit("New York"), F.lit("Austin"), F.lit("Chicago")),
        (F.col("id") % 4 + 1).cast("int"),
    ).alias("city"),
    F.format_string("%05d", 10000 + F.pmod(F.col("id") * 37, F.lit(89999))).alias(
        "postal_code"
    ),
)
products = spark.range(N_PRODUCTS, numPartitions=8).select(
    F.format_string("P%04d", F.col("id")).alias("product_key"),
    F.concat(F.lit("Product "), F.format_string("%04d", F.col("id"))).alias(
        "product_name"
    ),
    F.element_at(
        F.array(F.lit("Technology"), F.lit("Furniture"), F.lit("Office Supplies")),
        (F.col("id") % 3 + 1).cast("int"),
    ).alias("category"),
    F.element_at(
        F.array(
            F.lit("Accessories"),
            F.lit("Chairs"),
            F.lit("Storage"),
            F.lit("Phones"),
            F.lit("Tables"),
        ),
        (F.col("id") % 5 + 1).cast("int"),
    ).alias("subcategory"),
)
base_lines = spark.range(N_ORDER_LINES, numPartitions=16).select(
    F.col("id").alias("line_number"),
    F.format_string("L%08d", F.col("id")).alias("order_line_id"),
    F.format_string("O%07d", (F.col("id") / 3).cast("long")).alias("order_id"),
    F.format_string("C%05d", F.pmod(F.hash(F.col("id")), F.lit(N_CUSTOMERS))).alias(
        "customer_key"
    ),
    F.format_string("P%04d", F.pmod(F.hash(F.col("id") + 7), F.lit(N_PRODUCTS))).alias(
        "product_key"
    ),
    F.date_add(
        F.lit("2024-01-01").cast("date"),
        F.pmod(F.hash(F.col("id") + 13), F.lit(730)),
    ).alias("order_date"),
    (F.pmod(F.hash(F.col("id") + 17), F.lit(5)) + 1).cast("int").alias("quantity"),
    F.round(F.exp(F.randn(42) * F.lit(0.75) + F.lit(4.3)), 2).alias("unit_price"),
    F.when(F.pmod(F.hash(F.col("id") + 19), F.lit(10)) < 2, F.lit(0.20))
    .when(F.pmod(F.hash(F.col("id") + 19), F.lit(10)) < 5, F.lit(0.10))
    .otherwise(F.lit(0.0))
    .alias("discount_pct"),
)

legacy_lines = base_lines.select(
    "order_line_id",
    "order_id",
    "order_date",
    F.date_add("order_date", (F.pmod(F.hash("line_number"), F.lit(8)) + 1)).alias(
        "ship_date"
    ),
    "customer_key",
    "product_key",
    F.element_at(
        F.array(F.lit("Standard Class"), F.lit("Second Class"), F.lit("First Class"), F.lit("Same Day")),
        (F.pmod(F.hash("line_number"), F.lit(4)) + 1).cast("int"),
    ).alias("ship_mode"),
    "quantity",
    F.round(F.col("quantity") * F.col("unit_price"), 2).alias("gross_sales"),
    "discount_pct",
    F.round(
        F.col("quantity") * F.col("unit_price") * (1 - F.col("discount_pct")), 2
    ).alias("net_sales"),
    F.round(F.col("quantity") * F.col("unit_price") * F.lit(0.61), 2).alias(
        "cost"
    ),
).select(
    "*", F.round(F.col("net_sales") - F.col("cost"), 2).alias("profit")
)
order_returns = (
    legacy_lines
    .groupBy("order_id")
    .agg(
        F.max("ship_date").alias("last_ship_date"),
        F.min("product_key").alias("representative_product_key"),
        F.sum("net_sales").alias("order_sales"),
    )
    .join(
        products.select("product_key", "subcategory"),
        F.col("representative_product_key") == F.col("product_key"),
        "left",
    )
    .where(
        (F.pmod(F.hash("order_id"), F.lit(100)) < 6)
        | (
            (F.col("subcategory") == "Tables")
            & (F.pmod(F.hash("order_id", F.lit("tables")), F.lit(100)) < 16)
        )
    )
    .select(
        F.concat(F.lit("R"), F.substring("order_id", 2, 7)).alias("return_id"),
        "order_id",
        F.date_add(
            "last_ship_date", F.pmod(F.hash("order_id", F.lit("return-date")), F.lit(21)) + 1
        ).alias("return_date"),
        F.lit("Yes").alias("returned"),
        F.when(F.col("subcategory") == "Tables", "Damaged")
        .when(F.pmod(F.hash("order_id"), F.lit(3)) == 0, "Not needed")
        .when(F.pmod(F.hash("order_id"), F.lit(3)) == 1, "Wrong item")
        .otherwise("Quality issue")
        .alias("return_reason"),
        F.round(F.col("order_sales") * F.lit(0.92), 2).alias("refund_amount"),
    )
)
customer_base = customers
customer_original = customer_base.select(
    F.col("customer_key").alias("customer_id"),
    F.col("customer_name").alias("display_name"),
    F.col("segment").alias("customer_tier"),
    F.col("region").alias("sales_region"),
    F.col("country").alias("country_name"),
    F.col("state").alias("state_code"),
    F.col("city").alias("city_name"),
    "postal_code",
    F.lit("2020-01-01").cast("date").alias("business_valid_from"),
    F.when(F.col("customer_key").substr(2, 5).cast("int") % 50 == 0, F.lit("2025-07-01"))
    .otherwise(F.lit("9999-12-31"))
    .cast("date")
    .alias("business_valid_to"),
    F.lit("2024-01-01 00:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("9999-12-31 00:00:00").cast("timestamp").alias("system_recorded_to"),
)
changed_customers = customer_base.where(
    F.col("customer_key").substr(2, 5).cast("int") % 50 == 0
)
customer_changes_initial = changed_customers.select(
    F.col("customer_key").alias("customer_id"),
    F.col("customer_name").alias("display_name"),
    F.lit("Corporate").alias("customer_tier"),
    F.col("region").alias("sales_region"),
    F.col("country").alias("country_name"),
    F.col("state").alias("state_code"),
    F.col("city").alias("city_name"),
    "postal_code",
    F.lit("2025-07-01").cast("date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2025-07-15 09:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("2025-08-10 12:00:00").cast("timestamp").alias("system_recorded_to"),
)
customer_changes_corrected = changed_customers.select(
    F.col("customer_key").alias("customer_id"),
    F.col("customer_name").alias("display_name"),
    F.lit("Strategic").alias("customer_tier"),
    F.col("region").alias("sales_region"),
    F.col("country").alias("country_name"),
    F.col("state").alias("state_code"),
    F.col("city").alias("city_name"),
    "postal_code",
    F.lit("2025-07-01").cast("date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2025-08-10 12:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("9999-12-31 00:00:00").cast("timestamp").alias("system_recorded_to"),
)
write_table(
    customer_original.unionByName(customer_changes_initial).unionByName(
        customer_changes_corrected
    ),
    "customer_bitemporal",
)

product_base = products
corrected_products = product_base.where(
    F.col("product_key").substr(2, 4).cast("int") % 40 == 0
)
product_original = product_base.select(
    F.col("product_key").alias("product_id"),
    F.col("product_name").alias("product_label"),
    F.col("category").alias("product_category"),
    F.col("subcategory").alias("product_subcategory"),
    F.lit("2020-01-01").cast("date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2024-01-01 00:00:00").cast("timestamp").alias("system_recorded_from"),
    F.when(F.col("product_key").substr(2, 4).cast("int") % 40 == 0, F.lit("2025-08-10 12:00:00"))
    .otherwise(F.lit("9999-12-31 00:00:00"))
    .cast("timestamp")
    .alias("system_recorded_to"),
)
product_corrected = corrected_products.select(
    F.col("product_key").alias("product_id"),
    F.col("product_name").alias("product_label"),
    F.lit("Technology").alias("product_category"),
    F.col("subcategory").alias("product_subcategory"),
    F.lit("2020-01-01").cast("date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2025-08-10 12:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("9999-12-31 00:00:00").cast("timestamp").alias("system_recorded_to"),
)
write_table(product_original.unionByName(product_corrected), "product_bitemporal")

regional_managers = spark.createDataFrame(
    [
        ("West", "Morgan Lee", "2020-01-01", "2025-07-01", "2024-01-01 00:00:00", "9999-12-31 00:00:00"),
        ("West", "Avery Chen", "2025-07-01", "9999-12-31", "2025-07-15 09:00:00", "9999-12-31 00:00:00"),
        ("East", "Jordan Smith", "2020-01-01", "9999-12-31", "2024-01-01 00:00:00", "9999-12-31 00:00:00"),
        ("Central", "Taylor Brown", "2020-01-01", "9999-12-31", "2024-01-01 00:00:00", "9999-12-31 00:00:00"),
        ("South", "Riley Davis", "2020-01-01", "9999-12-31", "2024-01-01 00:00:00", "9999-12-31 00:00:00"),
    ],
    [
        "sales_region",
        "manager_name",
        "business_valid_from",
        "business_valid_to",
        "system_recorded_from",
        "system_recorded_to",
    ],
).select(
    "sales_region",
    "manager_name",
    F.col("business_valid_from").cast("date"),
    F.col("business_valid_to").cast("date"),
    F.col("system_recorded_from").cast("timestamp"),
    F.col("system_recorded_to").cast("timestamp"),
)
write_table(regional_managers, "regional_manager_assignment_bitemporal")

target_lines = legacy_lines.select(
    F.col("order_line_id").alias("sales_line_id"),
    F.col("order_id").alias("sales_order_id"),
    F.col("customer_key").alias("customer_id"),
    F.col("product_key").alias("product_id"),
    F.col("order_date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2026-01-05 08:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("9999-12-31 00:00:00").cast("timestamp").alias("system_recorded_to"),
    F.col("ship_date").alias("fulfilled_date"),
    F.col("ship_mode").alias("fulfillment_service_level"),
    F.col("quantity").alias("units_sold"),
    F.round(F.col("gross_sales") * 100).cast("long").alias("gross_amount_cents"),
    F.round((F.col("gross_sales") - F.col("net_sales")) * 100)
    .cast("long")
    .alias("discount_amount_cents"),
    F.round(F.col("net_sales") * 100).cast("long").alias("net_amount_cents"),
    F.round(F.col("cost") * 100).cast("long").alias("cost_amount_cents"),
)
write_table(target_lines, "sales_order_line_bitemporal")

return_events = order_returns.select(
    "return_id",
    F.col("order_id").alias("sales_order_id"),
    F.col("return_date").alias("business_valid_from"),
    F.lit("9999-12-31").cast("date").alias("business_valid_to"),
    F.lit("2026-01-05 08:00:00").cast("timestamp").alias("system_recorded_from"),
    F.lit("9999-12-31 00:00:00").cast("timestamp").alias("system_recorded_to"),
    "return_date",
    F.lit(True).alias("returned_flag"),
    F.lit("Returned").alias("return_status"),
    "return_reason",
    F.round(F.col("refund_amount") * 100).cast("long").alias("refund_amount_cents"),
)
write_table(return_events, "return_event_bitemporal")

if args.metadata_output:
    target_grains = {
        "sales_order_line_bitemporal": "one recorded version per sales order line and business-valid interval",
        "customer_bitemporal": "one recorded customer version per business-valid interval",
        "product_bitemporal": "one recorded product version per business-valid interval",
        "return_event_bitemporal": "one recorded return event per returned order and business-valid interval",
        "regional_manager_assignment_bitemporal": "one recorded regional manager assignment per business-valid interval",
    }
    metadata = {
        "tables": [
            {
                "name": f"{CATALOG}.{SCHEMA}.{table_name}",
                "grain": grain,
                "columns": [
                    {"name": field.name, "type": field.dataType.simpleString()}
                    for field in spark.table(f"{CATALOG}.{SCHEMA}.{table_name}").schema.fields
                ],
            }
            for table_name, grain in target_grains.items()
        ]
    }
    metadata_path = Path(args.metadata_output)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

print(
    f"Created repeatable Superstore importBI test data in {CATALOG}.{SCHEMA} "
    f"using profile {args.profile}"
)
