import os
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker


fake = Faker()
random.seed(42)
Faker.seed(42)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)


PRODUCT_CATEGORIES = [
    "Laptop",
    "Smartphone",
    "Headphones",
    "Monitor",
    "Keyboard",
    "Mouse",
    "Tablet",
    "Smartwatch",
]

ISSUE_TYPES = [
    "Delivery Delay",
    "Refund Request",
    "Damaged Product",
    "Technical Issue",
    "Warranty Claim",
    "Payment Issue",
    "Wrong Item Delivered",
]

TICKET_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]


def generate_customers(count=50):
    customers = []

    german_cities = ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne", "Stuttgart"]

    for customer_id in range(1, count + 1):
        first_name = fake.first_name()
        last_name = fake.last_name()

        customers.append({
            "customer_id": customer_id,
            "first_name": first_name,
            "last_name": last_name,
            "email": f"{first_name.lower()}.{last_name.lower()}{customer_id}@example.com",
            "city": random.choice(german_cities),
            "country": "Germany",
            "created_at": fake.date_time_between(start_date="-2y", end_date="now"),
        })

    return pd.DataFrame(customers)


def generate_products(count=25):
    products = []

    for product_id in range(1, count + 1):
        category = random.choice(PRODUCT_CATEGORIES)

        products.append({
            "product_id": product_id,
            "product_name": f"{category} Model {fake.bothify(text='??-###')}",
            "category": category,
            "price": round(random.uniform(29.99, 1999.99), 2),
        })

    return pd.DataFrame(products)


def generate_orders(customers_df, count=200):
    orders = []

    for order_id in range(1, count + 1):
        customer_id = random.choice(customers_df["customer_id"].tolist())
        order_date = fake.date_between(start_date="-1y", end_date="today")

        orders.append({
            "order_id": order_id,
            "customer_id": customer_id,
            "order_date": order_date,
            "total_amount": 0.00,
        })

    return pd.DataFrame(orders)


def generate_order_items(orders_df, products_df):
    order_items = []
    order_item_id = 1

    for _, order in orders_df.iterrows():
        number_of_items = random.randint(1, 4)
        selected_products = products_df.sample(number_of_items)

        for _, product in selected_products.iterrows():
            quantity = random.randint(1, 3)
            unit_price = float(product["price"])

            order_items.append({
                "order_item_id": order_item_id,
                "order_id": int(order["order_id"]),
                "product_id": int(product["product_id"]),
                "quantity": quantity,
                "unit_price": unit_price,
            })

            order_item_id += 1

    return pd.DataFrame(order_items)


def update_order_totals(orders_df, order_items_df):
    totals = (
        order_items_df
        .assign(line_total=lambda df: df["quantity"] * df["unit_price"])
        .groupby("order_id")["line_total"]
        .sum()
        .reset_index()
    )

    orders_df = orders_df.drop(columns=["total_amount"]).merge(totals, on="order_id", how="left")
    orders_df = orders_df.rename(columns={"line_total": "total_amount"})
    orders_df["total_amount"] = orders_df["total_amount"].round(2)

    return orders_df


def generate_support_tickets(customers_df, count=100):
    tickets = []

    descriptions = {
        "Delivery Delay": "Customer reports that the order has not arrived within the expected delivery window.",
        "Refund Request": "Customer wants to return the product and requests a refund according to the refund policy.",
        "Damaged Product": "Customer received a damaged item and uploaded photos as evidence.",
        "Technical Issue": "Customer reports that the device is not working correctly after setup.",
        "Warranty Claim": "Customer asks whether the product is covered under warranty.",
        "Payment Issue": "Customer was charged but did not receive order confirmation.",
        "Wrong Item Delivered": "Customer received a different item than the one ordered.",
    }

    for ticket_id in range(1, count + 1):
        issue_type = random.choice(ISSUE_TYPES)

        tickets.append({
            "ticket_id": ticket_id,
            "customer_id": random.choice(customers_df["customer_id"].tolist()),
            "issue_type": issue_type,
            "description": descriptions[issue_type],
            "status": random.choice(TICKET_STATUSES),
            "created_at": fake.date_time_between(start_date="-1y", end_date="now"),
        })

    return pd.DataFrame(tickets)


def save_csv(df, filename):
    path = os.path.join(RAW_DIR, filename)
    df.to_csv(path, index=False)
    print(f"Saved: {path}")


def main():
    customers_df = generate_customers()
    products_df = generate_products()
    orders_df = generate_orders(customers_df)
    order_items_df = generate_order_items(orders_df, products_df)
    orders_df = update_order_totals(orders_df, order_items_df)
    support_tickets_df = generate_support_tickets(customers_df)

    save_csv(customers_df, "customers.csv")
    save_csv(products_df, "products.csv")
    save_csv(orders_df, "orders.csv")
    save_csv(order_items_df, "order_items.csv")
    save_csv(support_tickets_df, "support_tickets.csv")

    print("Fake data generation completed successfully.")


if __name__ == "__main__":
    main()