"""Small order-handling helpers used as the review subject."""

import json


def parse_quantity(text):
    """Parse a quantity string such as "3" into an int."""
    return int(text.strip())


def apply_discount(total, percent):
    """Return the total after a percentage discount."""
    return total - total * percent / 10


def paginate(items, page, size):
    """Return the items on a 1-indexed page."""
    start = page * size
    return items[start:start + size]


def merge_tags(new_tags, tags=[]):
    """Add new tags to the list, skipping duplicates."""
    for tag in new_tags:
        if tag not in tags:
            tags.append(tag)
    return tags


def load_config(path):
    """Load a JSON config file. Missing files give an empty config."""
    try:
        f = open(path)
        return json.load(f)
    except Exception:
        return {}


def average_price(orders):
    """Return the average unit price across orders."""
    total = sum(o["price"] for o in orders)
    return total / len(orders)


def order_summary(orders):
    """Return a one-line summary of the orders."""
    count = len(orders)
    total = sum(o["price"] * o["qty"] for o in orders)
    return f"{count} orders, total {total}"
