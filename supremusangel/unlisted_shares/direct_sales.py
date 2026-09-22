"""Direct Sales enforcement for Unlisted Shares invoices.

The company price and customer price range come from the deal's price row, and the share
quota from the partner's access row, both on Item Price (Direct Sales list); see direct_ladder.py.
"""
import frappe
from frappe.utils import flt

from supremusangel.unlisted_shares.direct_ladder import (
    GROUP,
    deal_price_for,
    get_rate,
    invoice_rows,
    sold_quantity,
    sync_sold_quantity,
)


def validate_invoice(doc, method=None):
    # Direct sales pricing runs only when the invoice is ticked as Direct Sales.
    if not doc.get("custom_unlisted_shares") or doc.is_return or not doc.get("custom_direct_sales"):
        return

    items = get_share_items(doc)
    if len({row.item_code for row in items}) != 1:
        frappe.throw("A Direct Sales invoice must contain exactly one deal.")
    item_code = items[0].item_code

    if not deal_price_for(item_code, doc.posting_date):
        frappe.throw(f"{item_code} has no direct sales price on this date. "
                     "Untick Direct Sales to use Tier Commission instead.")
    rate = get_rate(item_code, doc.custom_primary_agent, doc.posting_date)
    if not rate:
        frappe.throw(f"No Sales Partner at or above {doc.custom_primary_agent} may sell {item_code}. "
                     "Untick Direct Sales to use Tier Commission instead.")

    qty = sum(flt(row.qty) for row in items)
    if qty <= 0:
        frappe.throw("Direct Sales quantity must be greater than zero.")

    low, high = flt(rate.custom_minimum_selling_rate), flt(rate.custom_maximum_selling_rate)
    for row in items:
        if not low <= flt(row.rate) <= high:
            frappe.throw(f"Rate for {row.item_code} must be between {low:g} and {high:g}.")

    partner = rate.custom_sales_partner
    already_sold = sold_quantity(item_code, partner, exclude_invoice=doc.name)
    if already_sold + qty > flt(rate.custom_reserved_qty):
        frappe.throw(f"Only {flt(rate.custom_reserved_qty) - already_sold:g} shares of {item_code} "
                     f"are left for {partner}.")

    doc.custom_direct_sales_partner = partner
    doc.custom_direct_sales_rate = rate.price_row
    doc.custom_company_settlement_rate = rate.company_price
    # Total earned by the whole agent ladder (rate - settlement rate); the per-agent
    # split is written to Sales Team by commission_engine.calculate.
    doc.custom_direct_sales_partner_earning = sum(amount for _, amount in invoice_rows(doc, rate))


def on_submit_invoice(doc, method=None):
    sync_from_invoice(doc)


def on_cancel_invoice(doc, method=None):
    sync_from_invoice(doc)


def sync_from_invoice(doc):
    if doc.get("custom_direct_sales") and doc.get("custom_direct_sales_partner"):
        for item_code in {row.item_code for row in get_share_items(doc)}:
            sync_sold_quantity(item_code, doc.custom_direct_sales_partner)


def get_share_items(doc):
    return [
        row for row in doc.get("items", [])
        if row.item_code and frappe.db.get_value("Item", row.item_code, "item_group") == GROUP
    ]
