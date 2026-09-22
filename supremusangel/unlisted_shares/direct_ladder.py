"""Direct Sales price ladder, configured entirely on Item Price.

Runs only on invoices with the **Direct Sales** checkbox ticked. Unticked share
invoices keep the percentage Tier Commission.

Everything lives in one selling price list, **Direct Sales**, as three kinds of row:

- **Deal price** (no Agent, no Sales Partner): the deal's prices from ``valid_from``.
  Rate = the company's base price; Minimum / Maximum Selling Rate = the customer price
  range. A later ``valid_from`` is a price change; older rows are the price history.
- **Partner access** (``custom_sales_partner`` set): lets that agent and everyone below
  them sell the deal, up to Reserved Qty. Sold / Remaining are kept up to date.
- **Agent price** (``custom_agent`` set): the price that agent charges their downline.

The partner buys at the company price. Each agent under them buys at their parent's agent
price; if the parent never set one they pass it on at cost (zero margin). The seller sets
the customer rate on the invoice. Every agent in the chain earns::

    (price the next agent down paid, or the customer rate) - own buy price

A missing tier is simply absent from the chain, so the seller keeps the gap. Margins are
written to the standard Sales Team rows as ``incentives``, the same commission ledger the
reports and Withdrawal Requests already read.
"""
import frappe
from erpnext.stock.doctype.item_price.item_price import ItemPrice, ItemPriceDuplicateItem
from frappe.utils import flt, getdate, nowdate

DIRECT_SALES_LIST = "Direct Sales"
GROUP = "Unlisted Shares"


def fail(message):
    frappe.throw(message)


def ancestors(agent):
    """[agent, parent, grandparent, ...] up the Sales Person tree."""
    chain, seen = [], set()
    while agent and agent not in seen:
        seen.add(agent)
        chain.append(agent)
        agent = frappe.db.get_value("Sales Person", agent, "parent_sales_person")
    return chain


def chain_to_partner(seller, partner):
    """[seller, ..., partner]. Fails if the seller is not in the partner's downline."""
    chain = ancestors(seller)
    if partner not in chain:
        fail(f"{seller} is not in the downline of Direct Sales Partner {partner}.")
    return chain[: chain.index(partner) + 1]


def row_kind(doc):
    if doc.get("custom_agent"):
        return "agent"
    if doc.get("custom_sales_partner"):
        return "partner"
    return "deal"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _in_force(rows, on_date):
    on_date = getdate(on_date or nowdate())
    for row in rows:  # newest Valid From first
        if (not row.valid_from or getdate(row.valid_from) <= on_date) and (
            not row.valid_upto or getdate(row.valid_upto) >= on_date
        ):
            return row
    return None


def deal_price_for(item_code, on_date=None):
    """The deal's price row in force on ``on_date`` (latest Valid From wins)."""
    return _in_force(frappe.get_all(
        "Item Price",
        filters={"price_list": DIRECT_SALES_LIST, "item_code": item_code,
                 "custom_agent": ["is", "not set"], "custom_sales_partner": ["is", "not set"]},
        fields=["name", "item_code", "price_list_rate", "custom_minimum_selling_rate",
                "custom_maximum_selling_rate", "valid_from", "valid_upto"],
        order_by="valid_from desc, creation desc",
    ), on_date)


def partner_access_for(item_code, partner, on_date=None):
    """The partner's access row for a deal in force on ``on_date``."""
    return _in_force(frappe.get_all(
        "Item Price",
        filters={"price_list": DIRECT_SALES_LIST, "item_code": item_code, "custom_sales_partner": partner},
        fields=["name", "custom_sales_partner", "custom_reserved_qty", "valid_from", "valid_upto"],
        order_by="valid_from desc, creation desc",
    ), on_date)


def _rate(price, access):
    """One view of what a sale needs: who the partner is and what the prices are."""
    return frappe._dict(
        item_code=price.item_code, custom_sales_partner=access.custom_sales_partner,
        company_price=flt(price.price_list_rate),
        custom_minimum_selling_rate=flt(price.custom_minimum_selling_rate),
        custom_maximum_selling_rate=flt(price.custom_maximum_selling_rate),
        custom_reserved_qty=flt(access.custom_reserved_qty),
        price_row=price.name, access_row=access.name,
    )


def get_rate(item_code, seller, on_date=None, price=None):
    """Prices plus the nearest partner at or above the seller allowed to sell the deal."""
    price = price or deal_price_for(item_code, on_date)
    if not price:
        return None
    for partner in ancestors(seller):
        access = partner_access_for(item_code, partner, on_date)
        if access:
            return _rate(price, access)
    return None


def rate_for_partner(item_code, partner, on_date=None):
    price, access = deal_price_for(item_code, on_date), partner_access_for(item_code, partner, on_date)
    return _rate(price, access) if price and access else None


def transfer_price(item_code, agent):
    """Price ``agent`` charges their downline, or None if they never set one."""
    rate = frappe.db.get_value(
        "Item Price",
        {"price_list": DIRECT_SALES_LIST, "item_code": item_code, "custom_agent": agent},
        "price_list_rate",
        order_by="modified desc",
    )
    return None if rate is None else flt(rate)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------
def buy_prices(chain, rate):
    """Buy price for each agent in ``chain`` (seller first, partner last)."""
    prices = [0.0] * len(chain)
    running = flt(rate.company_price)
    for i in range(len(chain) - 1, -1, -1):
        prices[i] = running
        if i:
            price = transfer_price(rate.item_code, chain[i])
            running = running if price is None else price
    return prices


def split(seller, rate, qty, sale_rate):
    """Margin rows for one sale line, seller first. Enforces every buy price in the chain."""
    chain = chain_to_partner(seller, rate.custom_sales_partner)
    buy = buy_prices(chain, rate)
    sale_rate, qty = flt(sale_rate), flt(qty)
    if sale_rate < buy[0]:
        fail(f"Rate {sale_rate:g} is below {seller}'s buy price of {buy[0]:g}.")
    rows = []
    for i, agent in enumerate(chain):
        sell = sale_rate if i == 0 else buy[i - 1]
        if sell < buy[i]:
            # An upline price set before a price change can now sit below that agent's cost.
            fail(f"{agent}'s price to their downline ({sell:g}) is below their own buy price ({buy[i]:g}) "
                 f"after the latest price change. {agent} must update it before this sale.")
        rows.append({"sales_person": agent, "buy_price": buy[i], "sell_price": sell,
                     "margin": flt(sell - buy[i]), "amount": flt((sell - buy[i]) * qty, 2)})
    return rows


def invoice_rows(doc, rate):
    """Per-agent totals for all share lines of a direct sales invoice, seller first."""
    totals = {}
    for row in doc.items:
        if row.item_code != rate.item_code:
            continue
        for line in split(doc.custom_primary_agent, rate, row.qty, row.rate):
            totals[line["sales_person"]] = totals.get(line["sales_person"], 0) + line["amount"]
    return list(totals.items())


def rate_from_invoice(doc):
    """The prices and partner a saved Direct Sales invoice was booked with."""
    price = frappe.db.get_value("Item Price", doc.custom_direct_sales_rate,
                                ["name", "item_code", "price_list_rate", "custom_minimum_selling_rate",
                                 "custom_maximum_selling_rate"], as_dict=True)
    access = partner_access_for(price.item_code, doc.custom_direct_sales_partner, doc.posting_date) \
        or frappe._dict(custom_sales_partner=doc.custom_direct_sales_partner, custom_reserved_qty=0, name=None)
    return _rate(price, access)


def sold_quantity(item_code, partner, exclude_invoice=None):
    """Shares of a deal sold under a partner on approved Direct Sales invoices."""
    return flt(frappe.db.sql(
        """select coalesce(sum(sii.qty), 0) from `tabSales Invoice Item` sii
           join `tabSales Invoice` si on si.name = sii.parent and sii.parenttype = 'Sales Invoice'
           where si.docstatus = 1 and si.custom_direct_sales = 1 and si.custom_direct_sales_partner = %s
             and sii.item_code = %s and si.name != %s""",
        (partner, item_code, exclude_invoice or ""),
    )[0][0])


def sync_sold_quantity(item_code, partner):
    """Refresh Sold / Remaining on every access row of this partner and deal."""
    sold = sold_quantity(item_code, partner)
    for row in frappe.get_all("Item Price", filters={"price_list": DIRECT_SALES_LIST, "item_code": item_code,
                                                     "custom_sales_partner": partner},
                              fields=["name", "custom_reserved_qty"]):
        frappe.db.set_value("Item Price", row.name, {
            "custom_sold_qty": sold,
            "custom_remaining_qty": max(flt(row.custom_reserved_qty) - sold, 0),
        }, update_modified=False)


def stale_agent_prices(item_code, price=None):
    """Agent prices for a deal that fall outside [own buy price, max] at the deal's prices."""
    stale = []
    for row in frappe.get_all("Item Price", filters={"price_list": DIRECT_SALES_LIST, "item_code": item_code,
                                                     "custom_agent": ["is", "set"]},
                              fields=["custom_agent", "price_list_rate"]):
        rate = get_rate(item_code, row.custom_agent, price=price)
        if not rate:
            continue  # no longer under any partner for this deal
        own_buy = buy_prices(chain_to_partner(row.custom_agent, rate.custom_sales_partner), rate)[0]
        if flt(row.price_list_rate) < own_buy:
            stale.append((row.custom_agent, row.price_list_rate, f"below their buy price of {own_buy:g}"))
        elif flt(row.price_list_rate) > rate.custom_maximum_selling_rate:
            stale.append((row.custom_agent, row.price_list_rate,
                          f"above the maximum selling rate of {rate.custom_maximum_selling_rate:g}"))
    return stale


# ---------------------------------------------------------------------------
# Item Price hooks
# ---------------------------------------------------------------------------
def validate_item_price(doc, method=None):
    from supremusangel.unlisted_shares.permissions import agent_only, linked_agent
    if agent_only() and doc.get("custom_agent") != linked_agent():
        # Agents may only keep their own downline prices; never deal prices, access or others' prices.
        frappe.throw("You can only set your own downline price.", frappe.PermissionError)
    if doc.get("custom_agent") and doc.get("custom_sales_partner"):
        fail("Set either Agent (an agent's downline price) or Sales Partner (who may sell the deal), not both.")
    if doc.price_list != DIRECT_SALES_LIST:
        if doc.get("custom_agent") or doc.get("custom_sales_partner"):
            fail(f"Agent prices and Sales Partner access belong in the {DIRECT_SALES_LIST} price list.")
        return
    if frappe.db.get_value("Item", doc.item_code, "item_group") != GROUP:
        fail(f"{doc.item_code} is not an {GROUP} deal.")
    {"deal": validate_deal_price, "partner": validate_partner_access, "agent": validate_agent_price}[row_kind(doc)](doc)


def validate_deal_price(doc):
    company, low, high = flt(doc.price_list_rate), flt(doc.custom_minimum_selling_rate), \
        flt(doc.custom_maximum_selling_rate)
    if company <= 0 or low <= 0 or high <= 0:
        fail("Company Price, Minimum and Maximum Selling Rate must all be greater than zero.")
    if not company <= low <= high:
        fail("Prices must be in order: Company Price ≤ Minimum Selling Rate ≤ Maximum Selling Rate.")
    if not doc.valid_from:
        doc.valid_from = nowdate()
    doc.custom_reserved_qty = doc.custom_sold_qty = doc.custom_remaining_qty = 0


def validate_partner_access(doc):
    if not frappe.db.get_value("Sales Person", doc.custom_sales_partner, "enabled"):
        fail("Sales Partner must be an enabled Sales Person.")
    if flt(doc.custom_reserved_qty) <= 0:
        fail("Reserved Qty must be greater than zero.")
    if not doc.valid_from:
        doc.valid_from = nowdate()
    # Access carries no price of its own; the deal price row does.
    doc.price_list_rate = 0
    doc.custom_minimum_selling_rate = doc.custom_maximum_selling_rate = 0
    sold = sold_quantity(doc.item_code, doc.custom_sales_partner)
    doc.custom_sold_qty = sold
    doc.custom_remaining_qty = max(flt(doc.custom_reserved_qty) - sold, 0)


def validate_agent_price(doc):
    if not deal_price_for(doc.item_code):
        fail(f"{doc.item_code} has no deal price yet. Add one first (Direct Sales list, no Agent or Sales Partner).")
    rate = get_rate(doc.item_code, doc.custom_agent)
    if not rate:
        fail(f"No Sales Partner at or above {doc.custom_agent} may sell {doc.item_code}. "
             f"Give their partner access first.")
    own_buy = buy_prices(chain_to_partner(doc.custom_agent, rate.custom_sales_partner), rate)[0]
    price = flt(doc.price_list_rate)
    if price < own_buy:
        fail(f"Price {price:g} is below {doc.custom_agent}'s own buy price of {own_buy:g}.")
    if price > rate.custom_maximum_selling_rate:
        fail(f"Price {price:g} is above the maximum selling rate of {rate.custom_maximum_selling_rate:g}.")


def on_update_item_price(doc, method=None):
    """After a deal price in force is saved, list agent prices it has made stale."""
    if doc.price_list != DIRECT_SALES_LIST or row_kind(doc) != "deal" or doc.flags.skip_stale_warning:
        return
    price = deal_price_for(doc.item_code)
    if not price or price.name != doc.name:
        return  # a future-dated or historical row; warn when it takes effect
    stale = stale_agent_prices(doc.item_code, price)
    if stale:
        lines = "".join(f"<li>{agent}: {rate:g} is {reason}</li>" for agent, rate, reason in stale)
        frappe.msgprint(f"These agent prices no longer fit the new prices. Sales through them are blocked "
                        f"until they are updated:<ul>{lines}</ul>", title="Agent prices to update",
                        indicator="orange")


class AgentItemPrice(ItemPrice):
    """ERPNext's duplicate check ignores custom fields, so deal prices, partner access and
    agent prices for one deal in the Direct Sales list would collide. Scope the check by
    kind: deal prices against deal prices, each partner and each agent against their own."""

    def check_duplicates(self):
        agent, partner = self.get("custom_agent"), self.get("custom_sales_partner")
        if self.price_list != DIRECT_SALES_LIST:
            return super().check_duplicates()
        filters = {"item_code": self.item_code, "price_list": self.price_list,
                   "custom_agent": agent or ("is", "not set"),
                   "custom_sales_partner": partner or ("is", "not set"), "name": ("!=", self.name)}
        for field in ("uom", "valid_from", "valid_upto", "customer", "supplier", "batch_no"):
            filters[field] = self.get(field) or ("is", "not set")
        if frappe.db.exists("Item Price", filters):
            frappe.throw("This agent already has a price for this deal." if agent else
                         "This partner already has access to this deal from the same date." if partner else
                         "This deal already has a price from the same date.", ItemPriceDuplicateItem)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _resolve_agent(sales_person=None):
    """The session user's agent; Admins may act for any agent they name."""
    from supremusangel.unlisted_shares.permissions import is_admin, linked_agent
    if sales_person and is_admin():
        return sales_person
    agent = linked_agent()
    if sales_person and sales_person != agent:
        frappe.throw("You can only manage your own prices.", frappe.PermissionError)
    return agent


@frappe.whitelist()
def get_item_price_context():
    """For an agent opening the Item Price form: their Sales Person and the deals they
    sell. Empty for everyone else."""
    from supremusangel.unlisted_shares.permissions import agent_only
    if not agent_only():
        return {}
    data = get_downline_prices()
    return {"agent": data["agent"], "price_lists": [DIRECT_SALES_LIST], "deals": [d["deal"] for d in data["deals"]]}


@frappe.whitelist()
def get_downline_prices(sales_person=None):
    """Every deal this agent can sell today, with their buy price and downline price."""
    agent = _resolve_agent(sales_person)
    has_downline = bool(frappe.db.exists("Sales Person", {"parent_sales_person": agent}))
    items = frappe.get_all("Item Price", filters={"price_list": DIRECT_SALES_LIST,
                                                  "custom_sales_partner": ["in", ancestors(agent)]},
                           pluck="item_code", distinct=True)
    out = []
    for item_code in sorted(set(items)):
        rate = get_rate(item_code, agent)
        if not rate:
            continue
        chain = chain_to_partner(agent, rate.custom_sales_partner)
        out.append({
            "deal": item_code, "sales_partner": rate.custom_sales_partner,
            "buy_price": buy_prices(chain, rate)[0],
            "downline_price": transfer_price(item_code, agent),
            "minimum_selling_rate": rate.custom_minimum_selling_rate,
            "maximum_selling_rate": rate.custom_maximum_selling_rate,
        })
    return {"agent": agent, "has_downline": has_downline, "deals": out}


@frappe.whitelist()
def set_downline_price(item_code, price, sales_person=None):
    """Set the price an agent charges their downline for a deal (limits checked on Item Price)."""
    agent = _resolve_agent(sales_person)
    name = frappe.db.get_value("Item Price", {"price_list": DIRECT_SALES_LIST, "item_code": item_code,
                                              "custom_agent": agent})
    doc = frappe.get_doc("Item Price", name) if name else frappe.get_doc({
        "doctype": "Item Price", "price_list": DIRECT_SALES_LIST, "item_code": item_code, "custom_agent": agent})
    doc.price_list_rate = flt(price)
    doc.save(ignore_permissions=True)
    return {"agent": agent, "price": doc.price_list_rate}
