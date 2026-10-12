"""
The mock database of Agent to Infrastructure (agent_infrastructure.py): a small online
store in PostgreSQL, and the requests the agents carry out on it.

Every task starts from the same database: the rows below come from a fixed seed, so a row
a request names (a customer, an order number) is there in every run. The requests are
grouped by what they do to the database, which is what the experiment compares:
looking rows up, inserting, updating and deleting them, and reports over many rows.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

# A database that lives for one task, on a network without internet, holding only the rows below
USER = "agent"
PASSWORD = "mock-store"
DATABASE = "store"
PORT = 5432

TASKS_PER_CATEGORY = 15
TODAY = "2026-10-01"   # the date the insert requests use, after every seeded row

# What the agents are told about the tables
SCHEMA_TEXT = """\
customers(customer_id, name, email, city, joined)
products(product_id, name, category, price, stock)
orders(order_id, customer_id, placed_on, status)   status is pending, shipped, delivered or cancelled
order_items(order_id, product_id, quantity, unit_price)
tickets(ticket_id, customer_id, opened_on, subject, status)   status is open or closed"""

SCHEMA_SQL = """\
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    city TEXT NOT NULL,
    joined DATE NOT NULL
);
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    price NUMERIC(8, 2) NOT NULL,
    stock INTEGER NOT NULL
);
CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers,
    placed_on DATE NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE order_items (
    order_id INTEGER NOT NULL REFERENCES orders ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(8, 2) NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
CREATE TABLE tickets (
    ticket_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers,
    opened_on DATE NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL
);
"""

_FIRST = ["Amara", "Bruno", "Chen", "Dalia", "Elias", "Farah", "Goran", "Hana", "Ivo", "Jun"]
_LAST = ["Okafor", "Lindqvist", "Moreau", "Tanaka"]
_CITIES = ["Lisbon", "Austin", "Osaka", "Nairobi", "Toronto", "Leipzig", "Valencia", "Auckland"]
_PRODUCTS = [   # name, category, price, stock
    ("Desk lamp", "Office", 34.90, 42), ("Notebook set", "Office", 12.50, 160), ("Monitor stand", "Office", 48.00, 9),
    ("Whiteboard", "Office", 65.00, 14), ("Fountain pen", "Office", 27.30, 55), ("Filing box", "Office", 9.80, 7),
    ("Cast iron pan", "Kitchen", 39.90, 21), ("Chef knife", "Kitchen", 58.00, 18), ("Kettle", "Kitchen", 31.40, 5),
    ("Cutting board", "Kitchen", 22.00, 64), ("Spice rack", "Kitchen", 18.60, 30), ("Coffee grinder", "Kitchen", 44.90, 11),
    ("Trail backpack", "Outdoor", 89.00, 16), ("Camping stove", "Outdoor", 52.50, 8), ("Headlamp", "Outdoor", 24.90, 73),
    ("Water filter", "Outdoor", 36.00, 12), ("Sleeping mat", "Outdoor", 41.20, 4), ("Trekking poles", "Outdoor", 47.80, 26),
    ("USB hub", "Electronics", 29.90, 88), ("Webcam", "Electronics", 62.00, 13), ("Wireless mouse", "Electronics", 21.50, 120),
    ("Power bank", "Electronics", 38.40, 6), ("Bluetooth speaker", "Electronics", 54.00, 19), ("Keyboard", "Electronics", 72.90, 33),
]
_SUBJECTS = [
    "Package arrived damaged", "Wrong item in the order", "Refund not received", "Change the delivery address",
    "Invoice is missing", "Item out of stock after payment", "Discount code not applied", "Late delivery",
]
_STATUSES = ["pending", "shipped", "delivered", "delivered", "delivered", "cancelled"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September"]


def _build() -> tuple[dict, dict[str, list[str]]]:
    rng = random.Random(2609)
    names = [f"{first} {last}" for last in _LAST for first in _FIRST]
    customers = [
        (name, f"{name.lower().replace(' ', '.')}@example.com", rng.choice(_CITIES),
         date(2025, 1, 1) + timedelta(days=rng.randrange(365)))
        for name in names
    ]
    orders, items = [], []
    for order_id in range(1, 151):
        orders.append((rng.randrange(1, len(customers) + 1), date(2026, 1, 1) + timedelta(days=rng.randrange(273)),
                       rng.choice(_STATUSES)))
        for product_id in sorted(rng.sample(range(1, len(_PRODUCTS) + 1), rng.randint(1, 4))):
            items.append((order_id, product_id, rng.randint(1, 5), _PRODUCTS[product_id - 1][2]))
    tickets = [
        (rng.randrange(1, len(customers) + 1), date(2026, 3, 1) + timedelta(days=rng.randrange(210)),
         rng.choice(_SUBJECTS), rng.choice(["open", "open", "closed"]))
        for _ in range(45)
    ]
    data = {"customers": customers, "products": _PRODUCTS, "orders": orders, "order_items": items, "tickets": tickets}

    # The requests: built from rows that exist, by a generator of their own so that changing
    # one category's requests doesn't change another's
    pick = random.Random(31877)
    product_names = [p[0] for p in _PRODUCTS]
    order_ids = pick.sample(range(1, len(orders) + 1), 16)
    by_order: dict[int, list[int]] = {}
    for order_id, product_id, _, _ in items:
        by_order.setdefault(order_id, []).append(product_id)
    several = pick.sample([o for o, products in by_order.items() if len(products) > 1], 5)
    pending = pick.sample([n for n, o in enumerate(orders, 1) if o[2] == "pending"], 4)
    open_tickets = [n for n, t in enumerate(tickets, 1) if t[3] == "open"]
    new_people = ["Kofi Almeida", "Lena Brandt", "Mateo Rossi", "Noor Haddad", "Petra Novak"]
    new_products = [("Label printer", "Office", 79.00, 15), ("Salad bowl", "Kitchen", 16.40, 40),
                    ("Tent lantern", "Outdoor", 19.90, 25), ("Phone stand", "Electronics", 14.20, 60)]

    tasks = {
        "lookup": [
            *(f"Find the email address and the city of the customer named {name}." for name in pick.sample(names, 5)),
            *(f"What are the price and the stock of the product '{name}'?" for name in pick.sample(product_names, 4)),
            *(f"What is the status of order {n}, and on which date was it placed?" for n in order_ids[:3]),
            *(f"Which products are in order {n}, and in what quantity?" for n in order_ids[3:6]),
        ],
        "insert": [
            *(f"Register a new customer named {name}, with the email address {name.lower().replace(' ', '.')}@example.com, "
              f"living in {pick.choice(_CITIES)}, who joined on {TODAY}." for name in new_people),
            *(f"Add a new product called '{name}' to the {category} category, priced at {price:.2f} with {stock} in stock."
              for name, category, price, stock in new_products),
            *(f"Open a support ticket dated {TODAY} for the customer named {name}, with the subject '{subject}'."
              for name, subject in zip(pick.sample(names, 3), pick.sample(_SUBJECTS, 3))),
            *(f"Create a pending order dated {TODAY} for the customer named {name}, with {units} of '{product}'."
              for name, product, units in zip(pick.sample(names, 3), pick.sample(product_names, 3), ("2 units", "1 unit", "3 units"))),
        ],
        "update": [
            *(f"The customer named {name} moved to {pick.choice(_CITIES)}. Update their city." for name in pick.sample(names, 4)),
            *(f"Change the price of the product '{name}' to {pick.randrange(10, 90)}.50." for name in pick.sample(product_names, 4)),
            *(f"Mark order {n} as shipped." for n in pending),
            *(f"Close support ticket {n}." for n in pick.sample(open_tickets, 3)),
        ],
        "delete": [
            *(f"Delete support ticket {n}." for n in pick.sample(range(1, len(tickets) + 1), 5)),
            *(f"Remove the product '{product_names[pick.choice(by_order[n]) - 1]}' from order {n}." for n in several),
            *(f"Delete order {n} together with its items." for n in order_ids[6:11]),
        ],
        "report": [
            *(f"List every customer living in {city}, with their email address." for city in pick.sample(_CITIES, 3)),
            *(f"List every order placed in {month} 2026, with the customer's name and the order's status."
              for month in pick.sample(_MONTHS, 3)),
            *(f"List every product with fewer than {n} units in stock, lowest stock first." for n in (10, 20, 40)),
            "Report the number of orders in each status.",
            "Report how many units of each product were sold in all, highest first.",
            "Report the total amount each customer has spent, highest first.",
            "List every open support ticket with the customer's name and the date it was opened.",
            "Report the number of products and their average price in each category.",
            "Report the store's revenue for each month of 2026.",
        ],
    }
    assert all(len(requests) == TASKS_PER_CATEGORY for requests in tasks.values())
    return data, tasks


_DATA, TASKS = _build()


def _values(rows: list[tuple]) -> str:
    def literal(v) -> str:
        if isinstance(v, (int, float)):
            return f"{v:.2f}" if isinstance(v, float) else str(v)
        return "'" + str(v).replace("'", "''") + "'"
    return ",\n".join("    (" + ", ".join(literal(v) for v in row) + ")" for row in rows)


def seed_sql() -> str:
    """The script PostgreSQL runs when a task's database is created: the tables and their rows."""
    columns = {
        "customers": "name, email, city, joined",
        "products": "name, category, price, stock",
        "orders": "customer_id, placed_on, status",
        "order_items": "order_id, product_id, quantity, unit_price",
        "tickets": "customer_id, opened_on, subject, status",
    }
    inserts = "\n".join(f"INSERT INTO {table} ({cols}) VALUES\n{_values(_DATA[table])};" for table, cols in columns.items())
    return SCHEMA_SQL + "\n" + inserts + "\n"


def rows() -> dict[str, int]:
    return {table: len(found) for table, found in _DATA.items()}


def task_text(request: str) -> str:
    """What the agents are given: the tables, then the request."""
    return (
        "An online store keeps its data in a PostgreSQL database with these tables:\n"
        f"{SCHEMA_TEXT}\n\n"
        f"Request: {request}\n\n"
        "Carry out the request on the database with the query_db tool, then check the result with a query."
    )


# The same three agents for every task; under the star topology MARBLE's planner hands them their work
AGENTS = [
    ("agent1", "agent1 is the store's data engineer. agent1 writes the SQL statement the request needs and runs it "
               "with the query_db tool. agent1 always answers with a call to query_db, never with the statement alone."),
    ("agent2", "agent2 is the store's data analyst. agent2 looks up the rows the request is about with the query_db "
               "tool, so that the right ids and values are used. agent2 always answers with a call to query_db."),
    ("agent3", "agent3 is a reviewer. agent3 checks with a SELECT through the query_db tool that the request was "
               "carried out, and reports what the database holds now. agent3 always answers with a call to query_db."),
]
