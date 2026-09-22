"""Fail-closed Agent scoping, shared by lists, documents and script reports."""
import frappe


def is_admin(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(set(frappe.get_roles(user)) & {"System Manager", "Admin"})


def linked_agent(user=None):
    user = user or frappe.session.user
    rows = frappe.get_all("Sales Person", filters={"custom_agent_user": user, "enabled": 1}, pluck="name", limit=2)
    if len(rows) != 1:
        frappe.throw("Your user must be linked to exactly one enabled Sales Person.", frappe.PermissionError)
    return rows[0]


def agent_only(user=None):
    return not is_admin(user) and "Agent" in frappe.get_roles(user or frappe.session.user)


def query(doctype, user=None):
    if not agent_only(user):
        return ""
    try:
        agent = frappe.db.escape(linked_agent(user))
    except frappe.PermissionError:
        return "1=0"
    if doctype == "Sales Person":
        return f"name = {agent}"
    if doctype == "Direct Sales Rate Revision":
        return (
            f"`tabDirect Sales Rate Revision`.`mandate` in "
            f"(select name from `tabDirect Sales Mandate` where sales_partner = {agent})"
        )
    field = {"Sales Invoice": "custom_primary_agent", "Customer": "custom_sales_person",
             "Payment Entry": "custom_sales_person", "Withdrawal Request": "sales_person",
             "Direct Sales Mandate": "sales_partner", "Item Price": "custom_agent"}[doctype]
    return f"`tab{doctype}`.`{field}` = {agent}"


def invoice_query(user=None): return query("Sales Invoice", user)
def customer_query(user=None): return query("Customer", user)
def person_query(user=None): return query("Sales Person", user)
def payment_query(user=None): return query("Payment Entry", user)
def withdrawal_query(user=None): return query("Withdrawal Request", user)
def direct_sales_mandate_query(user=None): return query("Direct Sales Mandate", user)
def direct_sales_rate_revision_query(user=None): return query("Direct Sales Rate Revision", user)
def item_price_query(user=None): return query("Item Price", user)


def has_permission(doc, user=None, permission_type=None):
    if not agent_only(user):
        return None
    try:
        agent = linked_agent(user)
    except frappe.PermissionError:
        return False
    if doc.doctype == "Direct Sales Rate Revision":
        return frappe.db.get_value("Direct Sales Mandate", doc.mandate, "sales_partner") == agent
    field = {"Sales Invoice": "custom_primary_agent", "Customer": "custom_sales_person",
             "Payment Entry": "custom_sales_person", "Withdrawal Request": "sales_person",
             "Direct Sales Mandate": "sales_partner", "Item Price": "custom_agent"}.get(doc.doctype)
    return (doc.name if doc.doctype == "Sales Person" else doc.get(field)) == agent
