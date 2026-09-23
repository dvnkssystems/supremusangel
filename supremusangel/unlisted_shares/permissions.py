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


# The field on each scoped doctype naming the agent a record belongs to.
AGENT_FIELD = {"Sales Invoice": "custom_primary_agent", "Customer": "custom_sales_person",
               "Payment Entry": "custom_sales_person", "Withdrawal Request": "sales_person",
               "Direct Sales Mandate": "sales_partner", "Item Price": "custom_agent"}
# An upline can look at (never change) these records of everyone below them in the tree.
# Money -- withdrawals and their payments -- stays private to each agent.
DOWNLINE_VISIBLE = {"Customer", "Sales Invoice", "Item Price"}
READ_ONLY_ACTIONS = {"read", "print", "report", "select"}


def downline_bounds(agent):
    """(lft, rgt) of the agent's subtree: themselves and everyone below them."""
    lft, rgt = frappe.db.get_value("Sales Person", agent, ["lft", "rgt"])
    return int(lft), int(rgt)


def in_downline(person, agent):
    if not person:
        return False
    lft, rgt = downline_bounds(agent)
    person_lft, person_rgt = frappe.db.get_value("Sales Person", person, ["lft", "rgt"]) or (0, 0)
    return lft <= person_lft and person_rgt <= rgt


def query(doctype, user=None):
    if not agent_only(user):
        return ""
    try:
        agent = linked_agent(user)
    except frappe.PermissionError:
        return "1=0"
    lft, rgt = downline_bounds(agent)
    if doctype == "Sales Person":
        return f"`tabSales Person`.`lft` >= {lft} and `tabSales Person`.`rgt` <= {rgt}"
    if doctype == "Direct Sales Rate Revision":
        return (
            f"`tabDirect Sales Rate Revision`.`mandate` in "
            f"(select name from `tabDirect Sales Mandate` where sales_partner = {frappe.db.escape(agent)})"
        )
    column = f"`tab{doctype}`.`{AGENT_FIELD[doctype]}`"
    if doctype in DOWNLINE_VISIBLE:
        return f"{column} in (select name from `tabSales Person` where lft >= {lft} and rgt <= {rgt})"
    return f"{column} = {frappe.db.escape(agent)}"


def invoice_query(user=None): return query("Sales Invoice", user)
def customer_query(user=None): return query("Customer", user)
def person_query(user=None): return query("Sales Person", user)
def payment_query(user=None): return query("Payment Entry", user)
def withdrawal_query(user=None): return query("Withdrawal Request", user)
def direct_sales_mandate_query(user=None): return query("Direct Sales Mandate", user)
def direct_sales_rate_revision_query(user=None): return query("Direct Sales Rate Revision", user)
def item_price_query(user=None): return query("Item Price", user)


def has_permission(doc, ptype=None, user=None):
    if not agent_only(user):
        return None
    try:
        agent = linked_agent(user)
    except frappe.PermissionError:
        return False
    if doc.doctype == "Direct Sales Rate Revision":
        return frappe.db.get_value("Direct Sales Mandate", doc.mandate, "sales_partner") == agent
    if doc.doctype == "Sales Person":
        if doc.is_new():
            # Adding a downline member: only somewhere below themselves.
            return in_downline(doc.parent_sales_person, agent)
        # An agent sees themselves and their whole downline.
        return in_downline(doc.name, agent)
    value = doc.get(AGENT_FIELD[doc.doctype])
    if doc.doctype == "Customer" and not value and doc.is_new():
        # The create check runs before any hook; assign_customer assigns the agent next.
        return True
    if doc.doctype in DOWNLINE_VISIBLE and ptype in READ_ONLY_ACTIONS:
        return in_downline(value, agent)
    return value == agent


def prepare_downline_member(doc, method=None):
    """A member an agent adds sits one tier below their parent, as the commission chain
    requires, and is paid by tier commission. Login, employee and rates are admin-only."""
    if not (agent_only() and doc.is_new()):
        return
    parent_tier = frappe.db.get_value("Sales Person", doc.parent_sales_person, "custom_tier")
    level = frappe.db.get_value("Commission Tier", parent_tier, "level") if parent_tier else None
    tier = level and frappe.db.get_value("Commission Tier", {"level": level - 1}, "name")
    if not tier:
        frappe.throw(f"{doc.parent_sales_person} is {parent_tier or 'not an agent'}, the first tier, so nobody "
                     f"can be added under them. Ask the admin for a promotion first.")
    doc.update(dict(custom_tier=tier, custom_use_tier_commission=1, is_group=int(level - 1 > 1), enabled=1,
                    employee=None, custom_agent_user=None, commission_rate=None))


def assign_customer(doc, method=None):
    """Keep a customer's Default Sales Person and Sales Team on the same person.

    A customer an agent creates or edits always stays with that agent. Whoever
    creates one, the Sales Team table is filled from the Default Sales Person (or
    the other way round), so the customer is credited to them in the tree.
    """
    if agent_only():
        doc.custom_sales_person = linked_agent()
    elif not doc.get("custom_sales_person") and doc.get("sales_team"):
        doc.custom_sales_person = doc.sales_team[0].sales_person
    person = doc.get("custom_sales_person")
    if person and person not in [r.sales_person for r in doc.get("sales_team") or []]:
        doc.set("sales_team", [dict(sales_person=person, allocated_percentage=100)])


@frappe.whitelist()
def get_tree_children(doctype, parent="", **filters):
    """An agent's Sales Person tree starts at their own node, not the company root."""
    from frappe.desk.treeview import get_children
    if doctype == "Sales Person" and not parent and agent_only():
        agent = linked_agent()
        return [dict(value=agent, title=agent, expandable=frappe.db.get_value("Sales Person", agent, "is_group"))]
    return get_children(doctype, parent, **filters)


@frappe.whitelist()
def get_agent_profile():
    """Who the signed-in agent is in the tree, for the header on the Agent Desk."""
    agent = linked_agent()
    sp = frappe.db.get_value("Sales Person", agent, ["sales_person_name", "custom_tier", "parent_sales_person",
                                                     "lft", "rgt"], as_dict=True)
    tier = frappe.db.get_value("Commission Tier", sp.custom_tier, ["level", "own_commission_percent",
                                                                  "direct_sale_commission_percent"], as_dict=True) or {}
    upline = sp.parent_sales_person
    if upline and not frappe.db.get_value("Sales Person", upline, "custom_tier"):
        upline = None  # the company root, not an agent
    return dict(agent=agent, name=sp.sales_person_name, tier=sp.custom_tier, level=tier.get("level"),
                tiers=frappe.get_all("Commission Tier", fields=["name", "level"], order_by="level asc"),
                own_percent=tier.get("own_commission_percent"),
                direct_percent=tier.get("direct_sale_commission_percent"),
                upline=upline, upline_tier=upline and frappe.db.get_value("Sales Person", upline, "custom_tier"),
                direct_team=frappe.db.count("Sales Person", {"parent_sales_person": agent}),
                team_size=(sp.rgt - sp.lft - 1) // 2)
