"""Idempotent metadata setup for fresh installs and existing-site migrations."""
import json
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Unlisted Shares"
REPORTS = ["Agent-wise Commission Summary", "Tier-wise Business Report", "Pending Approvals Report",
           "Top Customers by Value", "Referral Chain Drill-down", "My Sales and Commission",
           "My Downline Performance", "My Withdrawal History", "Direct Sales Partner Summary",
           "Direct Sales Commission"]


def field(name, label, kind="Link", options=None, **kwargs):
    return dict(fieldname=name, label=label, fieldtype=kind, options=options, **kwargs)


def setup():
    for role in ("Agent", "Admin"):
        if not frappe.db.exists("Role", role):
            frappe.get_doc(dict(doctype="Role", role_name=role, desk_access=1)).insert(ignore_permissions=True)
    create_custom_fields({
        "Sales Person": [field("custom_use_tier_commission", "Use Tier Commission", "Check", default="0",
                               insert_after="commission_rate", description="Enable the 30% tier commission scheme for this agent. Leave unchecked for existing monthly incentives."),
                         field("custom_tier", "Commission Tier", options="Commission Tier"),
                         field("custom_agent_user", "Agent User", options="User", unique=1)],
        "Customer": [field("custom_sales_person", "Default Sales Person", options="Sales Person")],
        "Item": [field("custom_logo", "Company Logo", "Attach Image")],
        "Sales Invoice": [field("custom_commission_scheme", "Commission Scheme", "Select", read_only=1,
                                options="\nMonthly Incentive\nTier Commission\nDirect Sales"),
                          field("custom_unlisted_shares", "Unlisted Shares", "Check", read_only=1, default="0"),
                          field("custom_primary_agent", "Primary Agent", options="Sales Person"),
                          field("custom_pending_since", "Pending Since", "Datetime", read_only=1),
                          field("custom_direct_sales_mandate", "Direct Sales Mandate", options="Direct Sales Mandate"),
                          field("custom_direct_sales_rate_revision", "Direct Sales Rate Revision", options="Direct Sales Rate Revision", read_only=1),
                          field("custom_company_settlement_rate", "Company Settlement Rate / Share", "Currency", read_only=1),
                          field("custom_direct_sales_partner_earning", "Direct Sales Partner Earning", "Currency", read_only=1)],
        "Item Price": [field("custom_agent", "Agent", options="Sales Person", insert_after="price_list",
                             description="Price this agent charges their downline for a Direct Sales Mandate deal.")],
        "Sales Team": [field("custom_commission_tier", "Commission Tier at Sale", options="Commission Tier", read_only=1)],
        "Payment Entry": [field("custom_sales_person", "Commission Agent", options="Sales Person", read_only=1),
                          field("custom_withdrawal_request", "Withdrawal Request", options="Withdrawal Request", read_only=1)],
    }, update=False)
    # Carry site-specific accounting dimensions into payment requests without
    # inventing a parallel accounting model (e.g. this demo site's Branch).
    from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
    dimensions = get_accounting_dimensions(as_list=False)
    if dimensions:
        create_custom_fields({"Withdrawal Request": [field(d.fieldname, d.label, options=d.document_type, permlevel=1)
                                                      for d in dimensions]}, update=False)
    if not frappe.db.exists("Item Group", "Unlisted Shares"):
        root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]}, "name") or "All Item Groups"
        frappe.get_doc(dict(doctype="Item Group", item_group_name="Unlisted Shares", parent_item_group=root)).insert(ignore_permissions=True)
    tiers = [("Associate", 1, 20, 20, []), ("Sr. Associate", 2, 5, 25, [("Associate", 5)]),
             ("Team Lead", 3, 3, 28, [("Sr. Associate", 3), ("Associate", 3)]),
             ("City Partner", 4, 2, 30, [("Team Lead", 2), ("Sr. Associate", 2), ("Associate", 2)])]
    for name, level, own_percent, direct_percent, overrides in tiers:
        if not frappe.db.exists("Commission Tier", name):
            frappe.get_doc(dict(doctype="Commission Tier", tier_name=name, level=level,
                own_commission_percent=own_percent, direct_sale_commission_percent=direct_percent,
                promotion_criteria="Administrator promotion after review of team performance.",
                overrides=[dict(from_tier=t, percent=p) for t, p in overrides])).insert(ignore_permissions=True)
    setup_direct_sales_fields()
    setup_direct_sales_price_list()
    add_columns_to_item_price_list_view()
    # Invoices booked against a mandate, or ticked on the retired Direct Sales checkbox,
    # before Is Direct Plan drove direct sales.
    frappe.db.sql("""update `tabSales Invoice` set custom_is_direct = 1
        where custom_is_direct = 0 and (custom_direct_sales = 1 or ifnull(custom_direct_sales_mandate, '') != '')""")
    migrate_mandates_to_item_price()
    split_rate_rows_into_deal_prices()
    # The direct sales scheme was renamed from "Direct Sales Mandate" to "Direct Sales".
    frappe.db.sql("""update `tabSales Invoice` set custom_commission_scheme = 'Direct Sales'
        where custom_commission_scheme = 'Direct Sales Mandate'""")
    setup_permissions()
    setup_workflows()
    setup_dashboard()


# Direct sales are configured on Item Price in the "Direct Sales" price list, as three kinds
# of row: the deal's price (no Agent, no Sales Partner), a partner's access and quota
# (Sales Partner set) and an agent's downline price (Agent set). These replace Direct Sales
# Mandate / Rate Revision. Applied with update=True on every migrate so existing sites
# pick up changes.
DEAL_ROW = "eval:doc.price_list=='Direct Sales' && !doc.custom_agent && !doc.custom_sales_partner"
DIRECT_SALES_FIELDS = {
    "Item Price": [
        field("custom_agent", "Agent", options="Sales Person", insert_after="price_list",
              in_list_view=1, in_standard_filter=1, depends_on="eval:doc.price_list=='Direct Sales' && !doc.custom_sales_partner",
              description="Set only for an agent's downline price: Rate is what this agent charges the people directly under them."),
        field("custom_sales_partner", "Sales Partner", options="Sales Person", insert_after="custom_agent",
              in_list_view=1, in_standard_filter=1, depends_on="eval:doc.price_list=='Direct Sales' && !doc.custom_agent",
              description="Set only to let this agent and everyone below them sell the deal, up to Reserved Qty. "
                          "Leave Agent and Sales Partner both empty for the deal's own prices."),
        field("custom_direct_sales_section", "Customer Price Range", "Section Break", insert_after="price_list_rate",
              depends_on=DEAL_ROW,
              description="Company Price above is the base price for this deal: what the Sales Partner buys at. "
                          "Customers pay between the minimum and maximum."),
        field("custom_minimum_selling_rate", "Minimum Selling Rate / Share", "Currency",
              insert_after="custom_direct_sales_section", mandatory_depends_on=DEAL_ROW),
        field("custom_maximum_selling_rate", "Maximum Selling Rate / Share", "Currency",
              insert_after="custom_minimum_selling_rate", mandatory_depends_on=DEAL_ROW,
              description="Highest price a customer can pay, and the ceiling for every agent's downline price."),
        # Retired: the company price is now the deal price row's Rate.
        field("custom_company_settlement_rate", "Company Settlement Rate / Share (old)", "Currency",
              insert_after="custom_maximum_selling_rate", hidden=1, mandatory_depends_on=""),
        field("custom_direct_sales_cb", "", "Column Break", insert_after="custom_company_settlement_rate", hidden=1),
        field("custom_partner_quota_section", "Partner Quota", "Section Break", insert_after="custom_direct_sales_cb",
              depends_on="custom_sales_partner"),
        field("custom_reserved_qty", "Reserved Qty", "Float", insert_after="custom_partner_quota_section",
              mandatory_depends_on="custom_sales_partner",
              description="Shares this partner and their tree may sell of this deal."),
        field("custom_partner_quota_cb", "", "Column Break", insert_after="custom_reserved_qty"),
        field("custom_sold_qty", "Sold Qty", "Float", insert_after="custom_partner_quota_cb", read_only=1, no_copy=1),
        field("custom_remaining_qty", "Remaining Qty", "Float", insert_after="custom_sold_qty", read_only=1, no_copy=1),
    ],
    "Sales Invoice": [
        field("custom_commission_scheme", "Commission Scheme", "Select", read_only=1,
              options="\nMonthly Incentive\nTier Commission\nDirect Sales"),
        # Same fieldname as the Sales Order's Is Direct Plan (customer_portal), so ERPNext
        # copies it onto the invoice made from the order.
        field("custom_is_direct", "Is Direct Plan", "Check", default="0", insert_after="custom_primary_agent",
              description="Price the sale through the direct sales ladder (rate minus each agent's buy price) instead of Tier Commission."),
        field("custom_direct_sales_partner", "Direct Sales Partner", options="Sales Person", read_only=1,
              insert_after="custom_is_direct", depends_on="custom_is_direct"),
        field("custom_direct_sales_rate", "Direct Sales Price", options="Item Price", read_only=1,
              insert_after="custom_direct_sales_partner", depends_on="custom_is_direct"),
        # Retired: replaced by Is Direct Plan; kept hidden so old values survive the migration.
        field("custom_direct_sales", "Direct Sales (old)", "Check", default="0", hidden=1, read_only=1),
        field("custom_company_settlement_rate", "Company Price / Share", "Currency", read_only=1),
        # Retired: kept read-only for invoices booked under the old mandate doctypes.
        field("custom_direct_sales_mandate", "Direct Sales Mandate (old)", options="Direct Sales Mandate",
              read_only=1, depends_on="custom_direct_sales_mandate"),
        field("custom_direct_sales_rate_revision", "Direct Sales Rate Revision (old)", options="Direct Sales Rate Revision",
              read_only=1, depends_on="custom_direct_sales_rate_revision"),
        field("custom_direct_sales_partner_earning", "Direct Sales Agent Earnings", "Currency", read_only=1,
              description="Total earned by all agents in the chain on this sale."),
    ],
}


def setup_direct_sales_fields():
    create_custom_fields(DIRECT_SALES_FIELDS, update=True)
    # ERPNext's quick-entry popup for Item Price shows only Item Code, which hides Agent,
    # Sales Partner and the price range; always open the full form instead.
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    make_property_setter("Item Price", None, "quick_entry", 0, "Check", for_doctype=True, validate_fields_for_doctype=False)
    # customer_portal makes the Sales Order's Is Direct Plan read-only (set by the investor
    # portal); let Desk users tick it too so their orders carry into Direct Sales invoices.
    make_property_setter("Sales Order", "custom_is_direct", "read_only", 0, "Check", validate_fields_for_doctype=False)


def setup_direct_sales_price_list():
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST
    if frappe.db.exists("Price List", DIRECT_SALES_LIST):
        return
    company = frappe.defaults.get_global_default("company")
    frappe.get_doc(dict(doctype="Price List", price_list_name=DIRECT_SALES_LIST, selling=1, enabled=1,
                        currency=frappe.db.get_value("Company", company, "default_currency") or "INR")
                   ).insert(ignore_permissions=True)


def add_columns_to_item_price_list_view():
    """A site's saved Item Price list columns override in_list_view, so add Agent and
    Sales Partner to them (after Price List) when missing. Existing columns are kept."""
    if not frappe.db.exists("List View Settings", "Item Price"):
        return
    settings = frappe.get_doc("List View Settings", "Item Price")
    fields = json.loads(settings.fields or "[]")
    if not fields:
        return
    changed = False
    for fieldname, label in (("custom_sales_partner", "Sales Partner"), ("custom_agent", "Agent")):
        if any(f.get("fieldname") == fieldname for f in fields):
            continue
        at = next((i + 1 for i, f in enumerate(fields) if f.get("fieldname") == "price_list"), len(fields))
        fields.insert(at, {"fieldname": fieldname, "label": label})
        changed = True
    if changed:
        settings.fields = json.dumps(fields)
        settings.total_fields = str(min(max(int(settings.total_fields or 4), len(fields)), 10))
        settings.save(ignore_permissions=True)


MIGRATED_FLAG = "supremusangel_direct_sales_on_item_price"
SPLIT_FLAG = "supremusangel_direct_sales_deal_price_split"


def _deal_price_key(item_code, valid_from):
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST
    return {"price_list": DIRECT_SALES_LIST, "item_code": item_code, "valid_from": valid_from,
            "custom_agent": ["is", "not set"], "custom_sales_partner": ["is", "not set"]}


def _upsert_deal_price(item_code, valid_from, company, low, high, note, overwrite):
    """Create the deal's price row for a date, or (when ``overwrite``) refresh it."""
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST
    values = dict(price_list_rate=company, custom_minimum_selling_rate=low, custom_maximum_selling_rate=high, note=note)
    name = frappe.db.get_value("Item Price", _deal_price_key(item_code, valid_from))
    if name:
        if overwrite:
            frappe.db.set_value("Item Price", name, values)
        return name
    doc = frappe.get_doc(dict(doctype="Item Price", price_list=DIRECT_SALES_LIST, item_code=item_code,
                              valid_from=valid_from, selling=1, **values))
    doc.flags.skip_stale_warning = True
    doc.insert(ignore_permissions=True)
    return doc.name


def migrate_mandates_to_item_price():
    """One-way copy of Direct Sales Mandates / Rate Revisions into Item Price: each revision
    becomes the deal's price row for its date, each mandate a partner access row with its
    quota, and agents' prices move from the mandate's own price list into Direct Sales.
    Runs once per site. The old records stay for history."""
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST, sync_sold_quantity
    if not frappe.db.exists("DocType", "Direct Sales Mandate") or frappe.db.get_default(MIGRATED_FLAG):
        return
    migrated = set()
    for mandate in frappe.get_all("Direct Sales Mandate", filters={"docstatus": 1},
                                  fields=["name", "sales_partner", "deal", "reserved_quantity", "price_list",
                                          "mandate_date"]):
        for rev in frappe.get_all("Direct Sales Rate Revision", filters={"mandate": mandate.name, "docstatus": 1},
                                  fields=["name", "effective_date", "company_settlement_rate",
                                          "minimum_selling_rate", "maximum_selling_rate"],
                                  order_by="effective_date asc, creation asc"):
            # Oldest first, so of two revisions on one date the later one wins.
            price = _upsert_deal_price(mandate.deal, rev.effective_date, rev.company_settlement_rate,
                                       rev.minimum_selling_rate, rev.maximum_selling_rate,
                                       f"Migrated from {mandate.name} / {rev.name}", overwrite=True)
            frappe.db.sql("""update `tabSales Invoice` set custom_direct_sales_partner = %s, custom_direct_sales_rate = %s
                where custom_direct_sales_rate_revision = %s""", (mandate.sales_partner, price, rev.name))
        if not frappe.db.exists("Item Price", {"price_list": DIRECT_SALES_LIST, "item_code": mandate.deal,
                                               "custom_sales_partner": mandate.sales_partner}):
            doc = frappe.get_doc(dict(doctype="Item Price", price_list=DIRECT_SALES_LIST, item_code=mandate.deal,
                                      selling=1, custom_sales_partner=mandate.sales_partner, price_list_rate=0,
                                      custom_reserved_qty=mandate.reserved_quantity, valid_from=mandate.mandate_date,
                                      note=f"Migrated from {mandate.name}"))
            doc.insert(ignore_permissions=True)
        if mandate.price_list and mandate.price_list != DIRECT_SALES_LIST:
            for row in frappe.get_all("Item Price", filters={"price_list": mandate.price_list, "item_code": mandate.deal,
                                                             "custom_agent": ["is", "set"]},
                                      fields=["custom_agent", "price_list_rate"]):
                if not frappe.db.exists("Item Price", {"price_list": DIRECT_SALES_LIST, "item_code": mandate.deal,
                                                       "custom_agent": row.custom_agent}):
                    doc = frappe.get_doc(dict(doctype="Item Price", price_list=DIRECT_SALES_LIST, selling=1,
                                              item_code=mandate.deal, custom_agent=row.custom_agent,
                                              price_list_rate=row.price_list_rate))
                    doc.flags.ignore_validate = True  # copied as-is; a stale price shows up in the price warning
                    doc.insert(ignore_permissions=True)
            # The mandate's own list is no longer read; switch it off so it can't be picked by mistake.
            frappe.db.set_value("Price List", mandate.price_list, "enabled", 0)
        migrated.add((mandate.deal, mandate.sales_partner))
    for deal, partner in migrated:
        sync_sold_quantity(deal, partner)
    # New mandates can no longer be created, so the copy only ever needs to run once.
    frappe.db.set_default(MIGRATED_FLAG, "1")
    frappe.db.set_default(SPLIT_FLAG, "1")  # rows above are already in the split layout


def split_rate_rows_into_deal_prices():
    """Sites migrated before the split kept prices on each partner's row. Move them to one
    deal price row per date, re-point invoices, and keep one access row per partner and deal
    (the latest). Runs once per site."""
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST, sync_sold_quantity
    if frappe.db.get_default(SPLIT_FLAG):
        return
    old_rows = frappe.get_all("Item Price", filters={"price_list": DIRECT_SALES_LIST,
                                                     "custom_sales_partner": ["is", "set"],
                                                     "custom_minimum_selling_rate": [">", 0]},
                              fields=["name", "item_code", "custom_sales_partner", "valid_from", "note",
                                      "custom_company_settlement_rate", "custom_minimum_selling_rate",
                                      "custom_maximum_selling_rate"],
                              order_by="valid_from asc, creation asc")
    latest, first_date = {}, {}
    for row in old_rows:
        first_date.setdefault((row.item_code, row.custom_sales_partner), row.valid_from)
        price = _upsert_deal_price(row.item_code, row.valid_from, row.custom_company_settlement_rate,
                                   row.custom_minimum_selling_rate, row.custom_maximum_selling_rate,
                                   row.note or f"Split from {row.name}", overwrite=False)
        frappe.db.sql("update `tabSales Invoice` set custom_direct_sales_rate = %s where custom_direct_sales_rate = %s",
                      (price, row.name))
        key = (row.item_code, row.custom_sales_partner)
        if key in latest and (latest[key].note or "").startswith("Migrated from"):
            # An older migrated copy of the same access; its prices now live on the deal price row.
            frappe.delete_doc("Item Price", latest[key].name, ignore_permissions=True, force=True)
        latest[key] = row
    for (item_code, partner), row in latest.items():
        # Access starts when the partner's earliest rate did, so older sales still find it.
        frappe.db.set_value("Item Price", row.name, {
            "price_list_rate": 0, "custom_company_settlement_rate": 0,
            "custom_minimum_selling_rate": 0, "custom_maximum_selling_rate": 0,
            "valid_from": first_date[(item_code, partner)],
        })
        sync_sold_quantity(item_code, partner)
    frappe.db.set_default(SPLIT_FLAG, "1")


def setup_permissions():
    from frappe.permissions import add_permission, update_permission_property
    for dt in ("Number Card", "Dashboard Chart", "Company", "Currency", "UOM", "Price List", "Item Group", "Customer Group", "Territory", "Account", "Cost Center"):
        for role in ("Agent", "Admin"):
            add_permission(dt, role, 0)
            update_permission_property(dt, role, 0, "read", 1)
    for dt in ("Supplier", "Branch"):
        if frappe.db.exists("DocType", dt):
            add_permission(dt, "Admin", 0)
            update_permission_property(dt, "Admin", 0, "read", 1)
    for dt in ["Sales Invoice", "Customer", "Sales Person", "Item", "Payment Entry", "Commission Tier", "Withdrawal Request",
               "Direct Sales Mandate", "Direct Sales Rate Revision"]:
        for role in ["Agent", "Admin"]:
            add_permission(dt, role, 0)
            rights = ["read", "report", "print"]
            if role == "Admin":
                rights += ["write", "create", "submit", "cancel", "amend", "export"]
            elif dt in ("Sales Invoice", "Withdrawal Request"):
                rights += ["write", "create"]
            for right in rights:
                update_permission_property(dt, role, 0, right, 1)
    # Agents edit only their own downline prices: rows are scoped by permissions.item_price_query
    # and direct_ladder.validate_item_price. No delete for agents.
    for role in ("Agent", "Admin"):
        add_permission("Item Price", role, 0)
        for right in ("read", "write", "create", "report"):
            update_permission_property("Item Price", role, 0, right, 1)


def make_workflow(name, doctype, states, transitions):
    other = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1, "name": ["!=", name]}, "name")
    if other:
        frappe.throw(f"Cannot install {name}: existing active workflow {other} needs integration.")
    for state, status, role in states:
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc(dict(doctype="Workflow State", workflow_state_name=state,
                                style="Success" if state in ("Approved", "Paid") else "Warning")).insert(ignore_permissions=True)
    for state, action, next_state, role, condition in transitions:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc(dict(doctype="Workflow Action Master", workflow_action_name=action)).insert(ignore_permissions=True)
    values = dict(doctype="Workflow", workflow_name=name, document_type=doctype,
        is_active=1, send_email_alert=0, workflow_state_field="workflow_state",
        states=[dict(state=s, doc_status=str(d), allow_edit=r) for s, d, r in states],
        transitions=[dict(state=s, action=a, next_state=n, allowed=r, condition=c, allow_self_approval=1)
                     for s, a, n, r, c in transitions])
    if frappe.db.exists("Workflow", name):
        doc = frappe.get_doc("Workflow", name)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc(values).insert(ignore_permissions=True)


def setup_workflows():
    make_workflow("SA Share Purchase Approval", "Sales Invoice",
        [("Draft", 0, "All"), ("Pending Approval", 0, "Admin"), ("Approved", 1, "Admin"),
         ("Rejected", 0, "Admin"), ("Cancelled", 2, "Admin")],
        [("Draft", "Request Approval", "Pending Approval", r, "doc.custom_unlisted_shares") for r in ("Agent", "Admin")]
        + [("Pending Approval", "Approve", "Approved", "Admin", "doc.custom_unlisted_shares"),
           ("Pending Approval", "Reject", "Rejected", "Admin", "doc.custom_unlisted_shares"),
           ("Rejected", "Revise", "Draft", "Admin", ""),
           ("Approved", "Cancel", "Cancelled", "Admin", "")]
        + [("Draft", "Submit", "Approved", r, "not doc.custom_unlisted_shares") for r in ("Accounts User", "Accounts Manager", "Admin")])
    make_workflow("SA Withdrawal Approval", "Withdrawal Request",
        [("Draft", 0, "Agent"), ("Pending Approval", 0, "Admin"), ("Approved", 1, "Admin"),
         ("Rejected", 0, "Admin"), ("Cancelled", 2, "Admin")],
        [("Draft", "Request Approval", "Pending Approval", r, "") for r in ("Agent", "Admin")]
        + [("Pending Approval", "Approve", "Approved", "Admin", ""),
           ("Pending Approval", "Reject", "Rejected", "Admin", ""),
           ("Rejected", "Revise", "Draft", "Admin", ""),
           ("Approved", "Cancel", "Cancelled", "Admin", "")])


def mark_pending(doc, method=None):
    old = doc.get_doc_before_save()
    if doc.get("custom_unlisted_shares") and doc.get("workflow_state") == "Pending Approval":
        if not old or old.get("workflow_state") != "Pending Approval":
            doc.custom_pending_since = frappe.utils.now_datetime()


def setup_dashboard():
    cards = [("SA Total Transactions", "Sales Invoice", [["Sales Invoice", "custom_unlisted_shares", "=", 1], ["Sales Invoice", "docstatus", "=", 1]]),
             ("SA Total Customers", "Customer", [["Customer", "custom_sales_person", "is", "set"]]),
             ("SA Active Deals", "Item", [["Item", "item_group", "=", "Unlisted Shares"], ["Item", "disabled", "=", 0]]),
             ("SA Pending Payment Requests", "Withdrawal Request", [["Withdrawal Request", "workflow_state", "=", "Pending Approval"]])]
    for name, dt, filters in cards:
        if not frappe.db.exists("Number Card", name):
            frappe.get_doc(dict(doctype="Number Card", name=name, label=name[3:], document_type=dt,
                                type="Document Type", function="Count", is_public=1,
                                filters_json=json.dumps(filters), module=MODULE)).insert(ignore_permissions=True, set_name=name)
    if not frappe.db.exists("Dashboard Chart", "SA Weekly Transaction Value"):
        frappe.get_doc(dict(doctype="Dashboard Chart", chart_name="SA Weekly Transaction Value", chart_type="Sum",
            document_type="Sales Invoice", based_on="posting_date", value_based_on="base_net_total", time_interval="Weekly",
            timespan="Last Quarter", type="Line", is_public=1, module=MODULE,
            filters_json=json.dumps([["Sales Invoice", "custom_unlisted_shares", "=", 1], ["Sales Invoice", "docstatus", "=", 1]]))).insert(ignore_permissions=True)
    # Extend the existing workspace; its salary incentive links remain available below.
    if not frappe.db.exists("Workspace", "Supremus Angel"):
        ws = frappe.get_doc(dict(doctype="Workspace", label="Supremus Angel", title="Supremus Angel", module="Supremus Angel", public=1, content="[]"))
    else:
        ws = frappe.get_doc("Workspace", "Supremus Angel")
    content = [r for r in json.loads(ws.content or "[]") if not r.get("id", "").startswith("shares_")]
    blocks = [dict(id="shares_header", type="header", data=dict(text="<b>Unlisted Shares</b>", col=12))]
    for name, dt, filters in cards:
        if not any(r.number_card_name == name for r in ws.number_cards): ws.append("number_cards", dict(number_card_name=name, label=name[3:]))
        blocks.append(dict(id="shares_card_" + frappe.scrub(name), type="number_card", data=dict(number_card_name=name[3:], col=3)))
    shortcuts = [("Agents", "Sales Person", "Tree", []), ("Deals", "Item", "List", [["Item", "item_group", "=", "Unlisted Shares"]]),
                 ("Customers", "Customer", "List", []), ("Transactions", "Sales Invoice", "List", [["Sales Invoice", "custom_unlisted_shares", "=", 1]]),
                 ("Direct Sales Rates", "Item Price", "List", [["Item Price", "price_list", "=", "Direct Sales"]]),
                 ("Commission Tiers", "Commission Tier", "List", []), ("Withdrawals", "Payment Entry", "List", [["Payment Entry", "custom_sales_person", "is", "set"]]),
                 ("Withdrawal Requests", "Withdrawal Request", "List", []),
                 ("Pending Approvals", "Sales Invoice", "List", [["Sales Invoice", "workflow_state", "=", "Pending Approval"]])]
    # Mandate and Rate Revision are retired in favour of Item Price rate rows.
    ws.set("shortcuts", [r for r in ws.shortcuts if r.link_to not in ("Direct Sales Mandate", "Direct Sales Rate Revision")])
    for label, dt, view, filters in shortcuts:
        if not any(r.label == label for r in ws.shortcuts): ws.append("shortcuts", dict(label=label, type="DocType", link_to=dt, doc_view=view, color="Blue", stats_filter=json.dumps(filters)))
        blocks.append(dict(id="shares_shortcut_" + frappe.scrub(label), type="shortcut", data=dict(shortcut_name=label, col=3)))
    if not any(r.chart_name == "SA Weekly Transaction Value" for r in ws.charts): ws.append("charts", dict(chart_name="SA Weekly Transaction Value", label="Weekly Transaction Value"))
    blocks.append(dict(id="shares_chart", type="chart", data=dict(chart_name="Weekly Transaction Value", col=12)))
    groups = {"Agent Network": [("Sales Person", "DocType"), ("Commission Tier", "DocType")],
              "Sales": [(n, "DocType") for n in ("Item", "Item Price", "Customer", "Sales Invoice", "Payment Entry", "Withdrawal Request")],
              "Share Commission Reports": [(n, "Report") for n in REPORTS]}
    retained, owned_group = [], False
    for row in ws.links:
        if row.type == "Card Break":
            owned_group = row.label in groups
        if not owned_group and row.link_to != "Commission Tier":
            retained.append(row)
    ws.set("links", retained)
    for group, entries in groups.items():
        if not any(r.label == group for r in ws.links):
            ws.append("links", dict(type="Card Break", label=group))
            for name, kind in entries: ws.append("links", dict(type="Link", label=name, link_type=kind, link_to=name, is_query_report=int(kind == "Report")))
        blocks.append(dict(id="shares_group_" + frappe.scrub(group), type="card", data=dict(card_name=group, col=4)))
    ws.content = json.dumps(blocks + content)
    current = None
    for index, row in enumerate(ws.links, 1):
        row.idx = index
        if row.type == "Card Break":
            current = row
            current.link_count = 0
        elif current:
            current.link_count += 1
    ws.save(ignore_permissions=True)
