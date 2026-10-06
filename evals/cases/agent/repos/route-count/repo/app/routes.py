from app.web import route


@route("/health")
def health():
    return "ok"


@route("/orders", methods=("GET", "POST"))
def orders():
    return []


@route("/orders/<id>")
def order(id):
    return {}


# Retired in v2; kept for reference.
# @route("/legacy/orders")
# def legacy_orders():
#     return []


@route("/customers")
def customers():
    return []


def helper():
    return "not a route"


@route("/customers/<id>", methods=("GET", "DELETE"))
def customer(id):
    return {}
