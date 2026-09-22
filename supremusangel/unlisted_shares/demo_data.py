"""Run explicitly: bench --site SITE execute supremusangel.unlisted_shares.demo_data.seed

Only synthetic demo entities are created. No demo records on normal install.
Stable names and invoice remarks make reruns safe; submitted invoices are real.
"""
from collections import Counter
import random
import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, today


def seed():
    from supremusangel.unlisted_shares.install import setup
    setup()
    counts = Counter()
    company = frappe.get_doc("Company", "Supremus Angel LLP") if frappe.db.exists("Company", "Supremus Angel LLP") else frappe.get_doc("Company", frappe.get_all("Company", pluck="name", limit=1)[0])
    branch = frappe.db.get_value("Branch", {}, "name") if frappe.db.exists("DocType", "Branch") else None
    def ensure(dt, name, values):
        if frappe.db.exists(dt, name):
            return frappe.get_doc(dt, name)
        doc = frappe.get_doc(dict(doctype=dt, **values))
        doc.insert(ignore_permissions=True)
        counts[dt] += 1
        return doc
    root = frappe.db.sql("select name from `tabSales Person` where is_group=1 and coalesce(parent_sales_person,'')='' limit 1")[0][0]
    city = ensure("Sales Person", "SA Demo - Meera Shah", dict(sales_person_name="SA Demo - Meera Shah", parent_sales_person=root, is_group=1, custom_tier="City Partner"))
    associates, seniors, leads = [], [], []
    for t, leadname in enumerate(["Arjun Desai", "Kavya Rao"]):
        lead = ensure("Sales Person", f"SA Demo - {leadname}", dict(sales_person_name=f"SA Demo - {leadname}", parent_sales_person=city.name, is_group=1, custom_tier="Team Lead"))
        leads.append(lead.name)
        for s in range(3):
            name = f"SA Demo - Senior {t+1}.{s+1}"
            senior = ensure("Sales Person", name, dict(sales_person_name=name, parent_sales_person=lead.name, is_group=1, custom_tier="Sr. Associate"))
            seniors.append(senior.name)
            for a in range(3):
                name = f"SA Demo - Associate {t+1}.{s+1}.{a+1}"
                person = ensure("Sales Person", name, dict(sales_person_name=name, parent_sales_person=senior.name, is_group=0, custom_tier="Associate"))
                associates.append(person.name)
    # Demo agents earn through Tier Commission, which each agent must opt into.
    for person in [city.name] + leads + seniors + associates:
        frappe.db.set_value("Sales Person", person, "custom_use_tier_commission", 1)
    for email, person, first in [("sa.associate@example.test", associates[0], "Demo Associate"),
                                  ("sa.teamlead@example.test", leads[0], "Demo Team Lead"),
                                  ("sa.admin@example.test", None, "Demo Share Admin")]:
        user = ensure("User", email, dict(email=email, first_name=first, enabled=1, user_type="System User", send_welcome_email=0,
                                          roles=[dict(role="Agent" if person else "Admin")]))
        if person: frappe.db.set_value("Sales Person", person, "custom_agent_user", user.name)
    items = []
    for i, (name, rate) in enumerate([("Aurora Mobility Limited", 25000), ("Nexora Digital Limited", 18000), ("Pravaah Energy Limited", 32000), ("Sahyadri Foods Limited", 12500)]):
        code = f"DEMOISIN{i+1:04d}"
        item = ensure("Item", code, dict(item_code=code, item_name=name + " (Demo)", item_group="Unlisted Shares", stock_uom="Nos", is_stock_item=0,
                standard_rate=rate, item_defaults=[dict(company=company.name, income_account=company.default_income_account)]))
        items.append((item.name, rate))
    customers = []
    rng = random.Random(42)
    for i, name in enumerate(["Aarav Mehta", "Diya Joshi", "Rohan Kulkarni", "Ananya Patel", "Ishaan Shah", "Neha Deshmukh", "Vivaan Rao", "Priya Nair", "Kabir Jain", "Sara Khan", "Advait More", "Mira Kapoor"]):
        full = "SA Demo - " + name
        agent = associates[0] if i == 0 else rng.choice(associates)
        customer = ensure("Customer", full, dict(customer_name=full, customer_type="Individual", customer_group="Individual", territory="India",
              custom_sales_person=agent, sales_team=[dict(sales_person=agent, allocated_percentage=100)]))
        customers.append(customer)
    invoice_names = []
    for i in range(20):
        marker = f"SA-SHARES-DEMO-{i+1:02d}"
        existing = frappe.db.get_value("Sales Invoice", {"remarks": marker, "docstatus": ["!=", 2]}, "name")
        if existing:
            invoice_names.append(existing)
            continue
        customer = customers[i % len(customers)]
        code, rate = items[i % len(items)]
        invoice = frappe.get_doc(dict(doctype="Sales Invoice", customer=customer.name, company=company.name,
            posting_date=add_days(today(), -(i * 2)), due_date=today(), set_posting_time=1,
            debit_to=company.default_receivable_account, currency=company.default_currency, conversion_rate=1,
            selling_price_list="Standard Selling", custom_primary_agent=customer.custom_sales_person,
            remarks=marker, branch=branch, items=[dict(item_code=code, qty=1+i%4, rate=rate, income_account=company.default_income_account,
                                     cost_center=company.cost_center)], taxes=[]))
        invoice.insert(ignore_permissions=True)
        invoice = apply_workflow(invoice, "Request Approval")
        if i < 18:
            invoice = apply_workflow(invoice, "Approve")
        invoice_names.append(invoice.name)
        counts["Sales Invoice"] += 1
    # Three withdrawals: two settled payments and one pending request.
    bank = frappe.db.get_value("Account", {"company": company.name, "account_type": "Bank", "is_group": 0}, "name")
    if not bank:
        parent = frappe.db.get_value("Account", {"company": company.name, "account_name": "Bank Accounts", "is_group": 1}, "name")
        bank = ensure("Account", "SA Demo Bank - " + company.abbr, dict(account_name="SA Demo Bank", company=company.name,
                      parent_account=parent, account_type="Bank", account_currency=company.default_currency)).name
    payable = frappe.db.get_value("Account", {"company": company.name, "account_type": "Payable", "is_group": 0}, "name")
    for i, person in enumerate([associates[0], leads[0], city.name]):
        marker = f"SA-SHARES-DEMO-WDR-{i+1}"
        if frappe.db.exists("Withdrawal Request", {"notes": marker}): continue
        supplier = ensure("Supplier", person, dict(supplier_name=person, supplier_type="Individual", supplier_group="All Supplier Groups"))
        w = frappe.get_doc(dict(doctype="Withdrawal Request", sales_person=person, company=company.name, amount=1000,
            posting_date=today(), supplier=supplier.name, paid_from=bank, paid_to=payable, branch=branch, notes=marker)).insert(ignore_permissions=True)
        w = apply_workflow(w, "Request Approval")
        if i < 2:
            w = apply_workflow(w, "Approve")
            pe = frappe.get_doc("Payment Entry", w.payment_entry)
            workflow = frappe.db.get_value("Workflow", {"document_type": "Payment Entry", "is_active": 1}, "name")
            if workflow:
                pe = apply_workflow(pe, "Approve")
            else:
                pe.submit()
            counts["Payment Entry"] += 1
        counts["Withdrawal Request"] += 1
    frappe.db.commit()
    summary = dict(created=dict(counts), totals={
        "Commission Tier": frappe.db.count("Commission Tier"),
        "Demo Sales Person": frappe.db.count("Sales Person", {"name": ["like", "SA Demo - %"]}),
        "Demo Item": frappe.db.count("Item", {"item_code": ["like", "DEMOISIN%"]}),
        "Demo Customer": frappe.db.count("Customer", {"customer_name": ["like", "SA Demo - %"]}),
        "Submitted Demo Sales Invoice": frappe.db.count("Sales Invoice", {"remarks": ["like", "SA-SHARES-DEMO-%"], "docstatus": 1}),
        "Pending Demo Sales Invoice": frappe.db.count("Sales Invoice", {"remarks": ["like", "SA-SHARES-DEMO-%"], "workflow_state": "Pending Approval"}),
        "Demo Withdrawal Request": frappe.db.count("Withdrawal Request", {"notes": ["like", "SA-SHARES-DEMO-WDR-%"]})},
        example_invoice=invoice_names[0], associate_user="sa.associate@example.test", team_lead_user="sa.teamlead@example.test")
    print(frappe.as_json(summary))
    return summary
