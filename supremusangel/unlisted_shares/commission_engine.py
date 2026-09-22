"""Auditable invoice commission ledger, using only core Sales Team rows.

Contribution remains 100% for the seller and 0% for ancestors (ERPNext requires
100% total). commission_rate is the actual payout percentage; incentives is
the rounded company-currency payout on base_net_total, excluding tax.
"""
import frappe
from frappe.utils import cint, flt
from supremusangel.unlisted_shares.schemes import DIRECT, MONTHLY, TIER, uses_tier_commission

GROUP = "Unlisted Shares"


def fail(message):
    frappe.log_error(title="Supremus Angel commission configuration", message=message)
    frappe.throw(message)


def is_share_invoice(doc):
    return any(frappe.db.get_value("Item", r.item_code, "item_group") == GROUP
               for r in doc.get("items", []) if r.item_code)


def prepare(doc, method=None):
    if doc.get("docstatus") == 2 or getattr(doc, "_action", None) == "update_after_submit":
        return
    previous_scheme = doc.get("custom_commission_scheme")
    share = is_share_invoice(doc)
    from supremusangel.unlisted_shares.permissions import agent_only
    if agent_only() and not share:
        frappe.throw("Agent transactions must contain unlisted share items.", frappe.PermissionError)
    was_share = doc.get("custom_unlisted_shares")
    doc.custom_unlisted_shares = int(share)
    if not share:
        doc.custom_commission_scheme = MONTHLY
        if was_share and doc.custom_primary_agent:
            doc.set("sales_team", [{"sales_person": doc.custom_primary_agent, "allocated_percentage": 100}])
        doc.custom_primary_agent = None
        return
    if any(frappe.db.get_value("Item", r.item_code, "item_group") != GROUP for r in doc.items):
        fail("Keep unlisted shares and other products on separate invoices.")
    if doc.is_return:
        fail("Cancel and amend the original share invoice; share credit notes are not supported.")
    if not doc.custom_primary_agent:
        doc.custom_primary_agent = (frappe.db.get_value("Customer", doc.customer, "custom_sales_person")
                                    or (doc.sales_team[0].sales_person if doc.sales_team else None))
    if not doc.custom_primary_agent:
        fail("Select a Primary Agent, or assign the customer's default Sales Person.")
    from supremusangel.unlisted_shares.permissions import is_admin, linked_agent
    if not is_admin() and doc.custom_primary_agent != linked_agent():
        frappe.throw("Agents can create transactions only for themselves.", frappe.PermissionError)
    # Direct Sales (price ladder) runs only when ticked; otherwise drop any stale
    # rate details so the invoice falls through to Tier / Monthly commission.
    if not doc.get("custom_direct_sales"):
        doc.custom_direct_sales_partner = None
        doc.custom_direct_sales_rate = None
        doc.custom_direct_sales_mandate = None
        doc.custom_direct_sales_rate_revision = None
        doc.custom_company_settlement_rate = 0
        doc.custom_direct_sales_partner_earning = 0
    if doc.get("custom_direct_sales"):
        doc.custom_commission_scheme = DIRECT
    elif uses_tier_commission(doc.custom_primary_agent):
        doc.custom_commission_scheme = TIER
    else:
        doc.custom_commission_scheme = MONTHLY
        if previous_scheme in (TIER, DIRECT) or (was_share and not previous_scheme):
            doc.set("sales_team", [{"sales_person": doc.custom_primary_agent, "allocated_percentage": 100}])
        return
    # Rebuild before core validation so its contribution validation always passes.
    doc.set("sales_team", [{"sales_person": doc.custom_primary_agent, "allocated_percentage": 100}])


def build_chain(seller):
    """Require consecutive tiers up to City Partner; never silently skip a gap."""
    result, seen, current = [], set(), seller
    previous_level = None
    while current:
        if current in seen:
            fail(f"Cycle in agent hierarchy at {current}.")
        seen.add(current)
        agent = frappe.db.get_value("Sales Person", current,
                                    ["name", "parent_sales_person", "custom_tier", "enabled"], as_dict=True)
        if not agent or not agent.enabled:
            fail(f"Missing or disabled agent: {current}.")
        if not uses_tier_commission(current):
            fail(f"Enable Use Tier Commission on Sales Person {current} before using this commission chain.")
        if not agent.custom_tier:
            fail(f"Commission Tier is missing on Sales Person {current}.")
        tier = frappe.get_doc("Commission Tier", agent.custom_tier)
        level = cint(tier.level)
        if previous_level is not None and level != previous_level + 1:
            fail(f"Broken hierarchy at {current}: parent must be exactly one tier higher.")
        if not result:
            rate = flt(tier.direct_sale_commission_percent)
        else:
            origin = result[0][2]
            rules = [r for r in tier.overrides if r.from_tier == origin]
            if len(rules) != 1:
                fail(f"Configure exactly one override from {origin} on tier {tier.name}.")
            rate = flt(rules[0].percent)
        if not 0 <= rate <= 100:
            fail(f"Invalid commission percentage on {tier.name}.")
        result.append((current, rate, tier.name))
        if level == 4:
            if agent.parent_sales_person and frappe.db.get_value("Sales Person", agent.parent_sales_person, "custom_tier"):
                fail("City Partner must be the highest commissioned agent.")
            break
        previous_level = level
        current = agent.parent_sales_person
        if not current:
            fail(f"Broken hierarchy above {agent.name}: a parent agent is required.")
    if not result or sum(r[1] for r in result) > 100:
        fail("Invalid commission chain or total commission exceeds 100%.")
    return result


def calculate(doc, method=None):
    if getattr(doc, "_action", None) == "update_after_submit":
        return
    if not doc.get("custom_unlisted_shares"):
        return
    if doc.get("custom_commission_scheme") == MONTHLY:
        return
    if doc.get("custom_direct_sales_rate"):
        amount = flt(doc.base_net_total)
        if amount <= 0:
            fail("Share invoice net value must be greater than zero.")
        # One row per agent up to the Sales Partner; incentives = their price margin.
        from supremusangel.unlisted_shares.direct_ladder import invoice_rows, rate_from_invoice
        rate = rate_from_invoice(doc)
        doc.set("sales_team", [{
            "sales_person": person,
            "allocated_percentage": 100 if index == 0 else 0,
            "allocated_amount": amount if index == 0 else 0,
            "commission_rate": "0",
            "incentives": flt(earning, 2),
            "custom_commission_tier": frappe.db.get_value("Sales Person", person, "custom_tier"),
        } for index, (person, earning) in enumerate(invoice_rows(doc, rate))])
        return
    if method == "before_submit":
        from supremusangel.unlisted_shares.permissions import is_admin
        if not is_admin() or doc.get("workflow_state") != "Approved":
            frappe.throw("Share invoices require Admin approval before submission.", frappe.PermissionError)
    chain = build_chain(doc.custom_primary_agent)
    amount = flt(doc.base_net_total)
    if amount <= 0:
        fail("Share invoice net value must be greater than zero.")
    existing = {r.sales_person: r for r in doc.sales_team}
    rows = []
    for index, (person, rate, tier) in enumerate(chain):
        row = existing.get(person)
        if row is None:
            row = doc.append("sales_team", {})
        row.sales_person = person
        row.allocated_percentage = 100 if index == 0 else 0
        row.allocated_amount = amount if index == 0 else 0
        row.commission_rate = str(rate)
        row.incentives = flt(amount * rate / 100, row.precision("incentives") or 2)
        row.custom_commission_tier = tier
        rows.append(row)
    doc.set("sales_team", rows)


def on_submit(doc, method=None):
    """The before_submit hook writes rows atomically; on_submit checks the ledger.

    App doc_events are versioned server code, not sandboxed UI Server Scripts.
    No second save or commit is performed inside the submit transaction.
    """
    if doc.get("custom_unlisted_shares"):
        stored = frappe.get_all("Sales Team", filters={"parent": doc.name, "parenttype": "Sales Invoice"},
                                fields=["sales_person", "incentives"])
        expected = {r.sales_person: flt(r.incentives) for r in doc.sales_team}
        if len(stored) != len(expected) or {r.sales_person: flt(r.incentives) for r in stored} != expected:
            fail(f"Commission ledger persistence failed for {doc.name}.")


def protect_submitted(doc, method=None):
    old = doc.get_doc_before_save()
    if old and old.get("custom_commission_scheme") != doc.get("custom_commission_scheme"):
        frappe.throw("The commission scheme on a submitted invoice cannot be changed.")
    if old and old.get("custom_unlisted_shares"):
        fields = ("sales_person", "allocated_percentage", "commission_rate", "incentives", "custom_commission_tier")
        if [tuple(r.get(f) for f in fields) for r in old.sales_team] != [tuple(r.get(f) for f in fields) for r in doc.sales_team]:
            frappe.throw("Submitted commission ledger is immutable. Cancel and amend the invoice.")
