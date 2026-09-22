"""Explicit agent opt-in and invoice-time incentive scheme selection."""
import frappe

TIER = "Tier Commission"
MONTHLY = "Monthly Incentive"
DIRECT = "Direct Sales"
LEGACY_DIRECT = "Direct Sales Mandate"  # value on invoices booked before the rename


def uses_tier_commission(sales_person):
    return bool(sales_person and frappe.db.get_value(
        "Sales Person", sales_person, "custom_use_tier_commission"
    ))


def require_monthly_agent(sales_person):
    if uses_tier_commission(sales_person):
        frappe.throw("This Sales Person uses Tier Commission. Monthly SA/TL/BM incentives do not apply.")


def is_monthly_invoice(doc):
    scheme = doc.get("custom_commission_scheme")
    return scheme == MONTHLY if scheme else not doc.get("custom_unlisted_shares")


def monthly_invoice_condition(alias="si"):
    # Blank snapshots retain the historical invoice classification.
    return (f"({alias}.custom_commission_scheme = 'Monthly Incentive' OR "
            f"(COALESCE({alias}.custom_commission_scheme, '') = '' "
            f"AND COALESCE({alias}.custom_unlisted_shares, 0) = 0))")
