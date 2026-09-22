"""Transactional acceptance checks. Run after demo_data.seed; mutations roll back."""
import frappe
from frappe.utils import add_days, today, flt
from frappe.model.workflow import apply_workflow
from supremusangel.unlisted_shares.commission_engine import calculate, build_chain
from supremusangel.unlisted_shares.reports import run_report
from supremusangel.unlisted_shares.install import REPORTS
from supremusangel.supremus_angel.incentive_source import get_sales_rows


def verify_direct_sales_demo():
    """Create/reuse the demo deal's Direct Sales setup on Item Price and book test invoices."""
    from supremusangel.unlisted_shares.direct_ladder import (DIRECT_SALES_LIST, deal_price_for,
                                                             partner_access_for)
    original = frappe.session.user
    frappe.set_user("Administrator")
    partner = "SA Demo - Arjun Desai"
    item = "DEMOISIN0001"
    company = "Supremus Angel LLP"
    customer = "Direct Sales Test Customer"
    results = {}
    try:
        if not frappe.db.exists("Customer", customer):
            frappe.get_doc({
                "doctype": "Customer",
                "customer_name": customer,
                "customer_type": "Individual",
                "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
                "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
                "custom_sales_person": partner,
            }).insert(ignore_permissions=True)

        def ensure_deal_price(valid_from, company_price, low, high):
            row = deal_price_for(item, valid_from)
            if row and str(row.valid_from) == valid_from:
                return row.name
            return frappe.get_doc({"doctype": "Item Price", "price_list": DIRECT_SALES_LIST, "item_code": item,
                                   "valid_from": valid_from, "price_list_rate": company_price,
                                   "custom_minimum_selling_rate": low, "custom_maximum_selling_rate": high,
                                   }).insert(ignore_permissions=True).name

        july_price = ensure_deal_price("2026-07-01", 11, 12, 15)
        september_price = ensure_deal_price("2026-09-01", 12, 13, 19)
        access = partner_access_for(item, partner, "2026-07-01")
        if not access:
            frappe.get_doc({"doctype": "Item Price", "price_list": DIRECT_SALES_LIST, "item_code": item,
                            "custom_sales_partner": partner, "custom_reserved_qty": 20000, "price_list_rate": 0,
                            "valid_from": "2026-07-01"}).insert(ignore_permissions=True)
            access = partner_access_for(item, partner, "2026-07-01")

        def make_invoice(remarks, posting_date, qty, rate):
            existing = frappe.db.get_value("Sales Invoice", {"remarks": remarks, "docstatus": 1}, "name")
            if existing:
                return frappe.get_doc("Sales Invoice", existing)
            doc = frappe.get_doc({
                "doctype": "Sales Invoice",
                "company": company,
                "customer": customer,
                "posting_date": posting_date,
                "set_posting_time": 1,
                "due_date": posting_date,
                "debit_to": frappe.db.get_value("Company", company, "default_receivable_account"),
                "custom_primary_agent": partner,
                "custom_is_direct": 1,
                "remarks": remarks,
                "branch": frappe.db.get_value("Branch", {}, "name"),
                "items": [{
                    "item_code": item,
                    "qty": qty,
                    "rate": rate,
                    "uom": frappe.db.get_value("Item", item, "stock_uom"),
                    "income_account": frappe.db.get_value("Company", company, "default_income_account"),
                    "cost_center": frappe.db.get_value("Company", company, "cost_center"),
                }],
            }).insert(ignore_permissions=True)
            doc = apply_workflow(doc, "Request Approval")
            return apply_workflow(doc, "Approve")

        invoice = make_invoice("DIRECT-SALES-TEST-13", "2026-07-05", 10, 13)
        invoice.reload()
        assert invoice.docstatus == 1
        assert invoice.custom_is_direct and invoice.custom_direct_sales_partner == partner
        assert invoice.custom_direct_sales_rate == july_price
        assert flt(invoice.custom_company_settlement_rate) == 11
        assert flt(invoice.custom_direct_sales_partner_earning) == 20
        assert len(invoice.sales_team) == 1
        assert invoice.sales_team[0].sales_person == partner
        assert flt(invoice.sales_team[0].commission_rate) == 0
        assert flt(invoice.sales_team[0].incentives) == 20

        september_invoice = make_invoice("DIRECT-SALES-TEST-16-SEPT", today(), 5, 16)
        september_invoice.reload()
        assert september_invoice.custom_direct_sales_rate == september_price
        assert flt(september_invoice.custom_company_settlement_rate) == 12
        assert flt(september_invoice.custom_direct_sales_partner_earning) == 20

        sold, remaining = frappe.db.get_value("Item Price", access.name, ["custom_sold_qty", "custom_remaining_qty"])
        assert flt(sold) >= 15 and flt(sold) + flt(remaining) == 20000

        if not frappe.db.exists("Sales Invoice", {"remarks": "DIRECT-SALES-TEST-CANCEL"}):
            before_remaining = flt(frappe.db.get_value("Item Price", access.name, "custom_remaining_qty"))
            cancel_invoice = make_invoice("DIRECT-SALES-TEST-CANCEL", today(), 3, 16)
            assert flt(frappe.db.get_value("Item Price", access.name, "custom_remaining_qty")) == before_remaining - 3
            apply_workflow(cancel_invoice, "Cancel")
            assert flt(frappe.db.get_value("Item Price", access.name, "custom_remaining_qty")) == before_remaining

        bad_invoice = frappe.copy_doc(invoice)
        bad_invoice.docstatus = 0
        bad_invoice.workflow_state = "Draft"
        bad_invoice.amended_from = None
        bad_invoice.remarks = "DIRECT-SALES-TEST-INVALID-RATE"
        bad_invoice.items[0].rate = 20
        try:
            bad_invoice.insert(ignore_permissions=True)
        except frappe.ValidationError:
            pass
        else:
            frappe.delete_doc("Sales Invoice", bad_invoice.name, force=True, ignore_permissions=True)
            raise AssertionError("Direct Sales invoice accepted a rate above the allowed range.")

        columns, rows = run_report("direct_sales", {"from_date": "2026-07-01", "to_date": today(), "sales_person": partner})
        assert columns and any(r.sales_partner == partner and r.deal == item and flt(r.agent_earning) >= 40 for r in rows)
        earned = frappe.db.sql("""select coalesce(sum(st.incentives),0) from `tabSales Team` st
            join `tabSales Invoice` si on si.name=st.parent and st.parenttype='Sales Invoice'
            where si.docstatus=1 and si.custom_unlisted_shares=1 and si.company=%s and st.sales_person=%s""",
            (company, partner))[0][0]
        assert flt(earned) >= 40

        frappe.set_user("sa.teamlead@example.test")
        own_prices = frappe.get_list("Item Price", filters={"price_list": DIRECT_SALES_LIST}, fields=["name", "custom_agent"],
                                     limit_page_length=100)
        assert all(r.custom_agent == partner for r in own_prices)
        assert run_report("direct_sales", {"from_date": "2026-07-01", "to_date": today()})[1]
        try:
            run_report("direct_sales", {"from_date": "2026-07-01", "to_date": today(), "sales_person": "SA Demo - Associate 1.1.1"})
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Agent could view another agent's Direct Sales report.")
        frappe.set_user("Administrator")

        sold, remaining = frappe.db.get_value("Item Price", access.name, ["custom_sold_qty", "custom_remaining_qty"])
        results.update({
            "july_deal_price": july_price,
            "september_deal_price": september_price,
            "partner_access": access.name,
            "invoice": invoice.name,
            "september_invoice": september_invoice.name,
            "selling_rate": 13,
            "company_rate": 11,
            "qty": 15,
            "agent_earnings": flt(invoice.custom_direct_sales_partner_earning) + flt(september_invoice.custom_direct_sales_partner_earning),
            "sold_quantity": sold,
            "remaining_quantity": remaining,
        })
        print(frappe.as_json(results))
        return results
    finally:
        frappe.set_user(original)


def dashboard_health():
    from frappe.desk.desktop import get_desktop_page
    frappe.set_user("sa.admin@example.test")
    result = get_desktop_page(frappe.as_json(dict(name="Supremus Angel", title="Supremus Angel", public=1)))
    return {"card_permission": frappe.has_permission("Number Card"), "chart_permission": frappe.has_permission("Dashboard Chart"),
            "number_cards": [r.number_card_name for r in result.get("number_cards", {}).get("items", [])],
            "charts": [r.chart_name for r in result.get("charts", {}).get("items", [])]}


def verify():
    original = frappe.session.user
    frappe.set_user("Administrator")
    results = {}
    f = dict(from_date=add_days(today(), -100), to_date=today())
    invoices = frappe.get_all("Sales Invoice", filters={"remarks": ["like", "SA-SHARES-DEMO-%"], "docstatus": 1}, pluck="name")
    assert len(invoices) == 18, f"Expected 18 submitted demo invoices, got {len(invoices)}"
    for name in invoices:
        doc = frappe.get_doc("Sales Invoice", name)
        assert [flt(r.commission_rate) for r in doc.sales_team] == [20, 5, 3, 2]
        assert len({r.sales_person for r in doc.sales_team}) == 4
        assert [flt(r.incentives) for r in doc.sales_team] == [flt(doc.base_net_total*p/100, 2) for p in [20,5,3,2]]
        calculate(doc)
        calculate(doc)
        assert len(doc.sales_team) == 4
        assert name not in [r.sales_invoice for r in get_sales_rows(doc.custom_primary_agent, f['from_date'], f['to_date'])]
    results["18 submitted invoices / cascade / idempotence / legacy exclusion"] = "PASS"
    f.update(sales_invoice=invoices[0], sales_person="SA Demo - Arjun Desai")
    kinds = ["agent_summary", "tier_business", "pending_approvals", "top_customers", "referral_chain", "my_sales", "my_downline", "my_withdrawals", "direct_sales"]
    for name, kind in zip(REPORTS, kinds):
        assert frappe.db.exists("Report", name)
        columns, rows = run_report(kind, f)
        assert columns and rows, f"Empty report: {name}"
        results[name] = len(rows)
    from frappe.desk.query_report import run
    for name in REPORTS:
        result = run(name, filters=f, ignore_prepared_report=True)
        assert result.get("result"), f"Report endpoint failed: {name}"
    results["All 8 standard Report endpoints"] = "PASS"
    # Permission checks run with an Agent-only identity, not System Manager.
    frappe.set_user("sa.associate@example.test")
    assert "System Manager" not in frappe.get_roles()
    own = "SA Demo - Associate 1.1.1"
    visible = frappe.get_list("Sales Invoice", fields=["name", "custom_primary_agent"], limit_page_length=100)
    assert visible and all(r.custom_primary_agent == own for r in visible)
    own_filters = dict(from_date=f["from_date"], to_date=f["to_date"])
    assert run_report("my_sales", own_filters)[1]
    assert run_report("my_withdrawals", own_filters)[1]
    for kind, filters in [("agent_summary", own_filters), ("my_sales", f), ("my_downline", own_filters)]:
        try:
            run_report(kind, filters)
        except (frappe.PermissionError, frappe.ValidationError):
            pass
        else:
            raise AssertionError(f"Unauthorized report allowed: {kind}")
    foreign = next(n for n in invoices if frappe.db.get_value("Sales Invoice", n, "custom_primary_agent") != own)
    assert not frappe.has_permission("Sales Invoice", "read", doc=foreign)
    assert not frappe.has_permission("Sales Invoice", "submit")
    results["Agent list / direct-document / spoofed-filter / Admin-report denial"] = "PASS"
    frappe.set_user("sa.teamlead@example.test")
    assert run_report("my_downline", own_filters)[1]
    results["Agent-only Team Lead downline report"] = "PASS"
    frappe.set_user("Administrator")
    frappe.db.savepoint("sa_acceptance")
    try:
        # Invalid chain must fail with an actionable error.
        frappe.db.set_value("Sales Person", own, "custom_tier", None)
        try:
            build_chain(own)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Missing tier accepted")
        frappe.db.rollback(save_point="sa_acceptance")
        frappe.db.savepoint("sa_acceptance")
        doc = frappe.get_doc("Sales Invoice", invoices[0])
        doc.sales_team[0].incentives = 999999
        try:
            doc.save()
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Submitted ledger modification accepted")
        results["Missing-tier rejection / submitted-ledger immutability"] = "PASS"
        frappe.db.rollback(save_point="sa_acceptance")
        frappe.db.savepoint("sa_acceptance")
        # Exercise real cancellation and amendment, then restore everything.
        cancelled = apply_workflow(frappe.get_doc("Sales Invoice", invoices[-1]), "Cancel")
        assert cancelled.docstatus == 2
        amended = frappe.copy_doc(cancelled)
        amended.docstatus = 0
        amended.workflow_state = "Draft"
        amended.amended_from = cancelled.name
        amended.remarks = "SA acceptance amendment (rolled back)"
        amended.insert()
        amended = apply_workflow(amended, "Request Approval")
        amended = apply_workflow(amended, "Approve")
        assert amended.docstatus == 1 and len(amended.sales_team) == 4
        results["Real cancellation / amendment / resubmission"] = "PASS"
        # Overdraft must fail at approval, including already reserved payouts.
        sample = frappe.get_doc("Withdrawal Request", frappe.db.get_value("Withdrawal Request", {"docstatus": 1}, "name"))
        excessive = frappe.copy_doc(sample)
        excessive.docstatus = 0
        excessive.workflow_state = "Draft"
        excessive.payment_entry = None
        excessive.amount = 999999999
        excessive.insert()
        excessive = apply_workflow(excessive, "Request Approval")
        try:
            apply_workflow(excessive, "Approve")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Overdraft approved")
        results["Withdrawal balance protection"] = "PASS"
        pending_request = frappe.db.get_value("Withdrawal Request", {"workflow_state": "Pending Approval", "notes": "SA-SHARES-DEMO-WDR-3"}, "name")
        approved_request = apply_workflow(frappe.get_doc("Withdrawal Request", pending_request), "Approve")
        draft_payment = approved_request.payment_entry
        assert frappe.db.get_value("Payment Entry", draft_payment, "docstatus") == 0
        apply_workflow(approved_request, "Cancel")
        assert not frappe.db.exists("Payment Entry", draft_payment)
        results["Unpaid withdrawal cancellation releases reservation and draft payment"] = "PASS"
    finally:
        frappe.db.rollback(save_point="sa_acceptance")
        frappe.set_user(original)
    print(frappe.as_json(results))
    return results
