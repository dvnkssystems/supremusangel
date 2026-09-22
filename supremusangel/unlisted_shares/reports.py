"""Report queries use submitted Sales Team rows as the only commission ledger."""
import frappe
from frappe.utils import add_months, flt, getdate, today
from supremusangel.unlisted_shares.permissions import is_admin, linked_agent


def col(label, fieldname, fieldtype="Currency", options=None, width=150):
    return dict(label=label, fieldname=fieldname, fieldtype=fieldtype, options=options, width=width)


AGENT = col("Sales Person", "sales_person", "Link", "Sales Person", 200)
TIER = col("Tier", "tier", "Link", "Commission Tier")
INVOICE = col("Sales Invoice", "sales_invoice", "Link", "Sales Invoice", 180)
DATE = col("Date", "posting_date", "Date", width=110)


def run_report(kind, filters=None):
    f = frappe._dict(filters or {})
    f.from_date = getdate(f.get("from_date") or add_months(today(), -3))
    f.to_date = getdate(f.get("to_date") or today())
    if f.from_date > f.to_date:
        frappe.throw("From Date must be before To Date.")
    if kind == "direct_commission":
        if not is_admin():
            agent = linked_agent()
            if f.get("sales_person") and f.sales_person != agent:
                frappe.throw("You cannot view another agent's commission.", frappe.PermissionError)
            f.sales_person = agent
    elif kind == "direct_sales":
        if not is_admin():
            agent = linked_agent()
            if f.get("sales_person") and f.sales_person != agent:
                frappe.throw("You cannot view another agent's direct sales.", frappe.PermissionError)
            f.sales_person = agent
    elif kind.startswith("my_"):
        if is_admin():
            if not f.get("sales_person"):
                frappe.throw("Select a Sales Person to preview an agent report.")
        else:
            agent = linked_agent()
            if f.get("sales_person") and f.sales_person != agent:
                frappe.throw("You cannot view another agent's report.", frappe.PermissionError)
            f.sales_person = agent
    elif not is_admin():
        frappe.throw("This report is restricted to Admin users.", frappe.PermissionError)
    return globals()[kind](f)


def sql(query, f):
    return frappe.db.sql(query, f, as_dict=True)


BASE = """from `tabSales Invoice` si join `tabSales Team` st on st.parent=si.name
    and st.parenttype='Sales Invoice' and st.parentfield='sales_team'
    where si.docstatus=1 and si.custom_unlisted_shares=1 and coalesce(si.custom_commission_scheme, '') != 'Monthly Incentive'
    and si.posting_date between %(from_date)s and %(to_date)s"""


def agent_summary(f):
    columns = [AGENT, TIER, col("Own Sales", "own_sales"), col("Own Commission", "own_commission"),
               col("Override Earned", "override_earned"), col("Combined Commission", "combined"), col("Currency", "currency", "Link", "Currency")]
    rows = sql("""select st.sales_person, st.custom_commission_tier tier, si.company,
        (select default_currency from tabCompany where name=si.company) currency,
        sum(case when st.sales_person=si.custom_primary_agent then si.base_net_total else 0 end) own_sales,
        sum(case when st.sales_person=si.custom_primary_agent then st.incentives else 0 end) own_commission,
        sum(case when st.sales_person!=si.custom_primary_agent then st.incentives else 0 end) override_earned,
        sum(st.incentives) combined """ + BASE + " group by st.sales_person,st.custom_commission_tier,si.company order by combined desc", f)
    return columns, rows


def tier_business(f):
    rows = sql("""select st.custom_commission_tier tier, si.company,
        sum(case when st.sales_person=si.custom_primary_agent then si.base_net_total else 0 end) business,
        sum(st.incentives) earned """ + BASE + " group by st.custom_commission_tier,si.company", f)
    counts = {r.custom_tier: r.count for r in sql("select custom_tier,count(*) count from `tabSales Person` where enabled=1 group by custom_tier", f)}
    paid = {(r.tier, r.company): r.paid for r in sql("""select sp.custom_tier tier,pe.company,sum(pe.base_paid_amount) paid
        from `tabPayment Entry` pe join `tabSales Person` sp on sp.name=pe.custom_sales_person
        where pe.docstatus=1 and pe.payment_type='Pay' and pe.posting_date between %(from_date)s and %(to_date)s
        group by sp.custom_tier,pe.company""", f)}
    for row in rows:
        row.agent_count = counts.get(row.tier, 0)
        row.paid = paid.get((row.tier, row.company), 0)
    return [TIER, col("Company", "company", "Link", "Company"), col("Business Generated", "business"),
            col("Commission Earned", "earned"), col("Commission Paid", "paid"), col("Agent Count", "agent_count", "Int")], rows


def pending_approvals(f):
    rows = sql("""select si.name sales_invoice,si.custom_primary_agent sales_person,si.customer,
        group_concat(distinct sii.item_name separator ', ') deal,si.base_net_total amount,
        datediff(curdate(),coalesce(si.custom_pending_since,si.creation)) days_pending,si.posting_date
        from `tabSales Invoice` si join `tabSales Invoice Item` sii on sii.parent=si.name
        where si.docstatus=0 and si.custom_unlisted_shares=1 and si.workflow_state='Pending Approval'
        and si.posting_date between %(from_date)s and %(to_date)s group by si.name order by days_pending desc""", f)
    return [INVOICE, DATE, AGENT, col("Customer", "customer", "Link", "Customer"), col("Deal", "deal", "Data", width=240),
            col("Net Value", "amount"), col("Days Pending", "days_pending", "Int")], rows


def top_customers(f):
    rows = sql("""select customer,company,count(*) transactions,sum(base_net_total) value from `tabSales Invoice`
        where docstatus=1 and custom_unlisted_shares=1 and posting_date between %(from_date)s and %(to_date)s
        group by customer,company order by value desc limit 20""", f)
    return [col("Customer", "customer", "Link", "Customer", 230), col("Company", "company", "Link", "Company"),
            col("Transactions", "transactions", "Int"), col("Total Value", "value")], rows


def referral_chain(f):
    if not f.get("sales_invoice"):
        frappe.throw("Select a Sales Invoice.")
    rows = sql("""select st.sales_person,st.custom_commission_tier tier,case when si.custom_commission_scheme='Direct Sales Mandate' then null else st.commission_rate end percent,st.incentives amount,
        case when st.sales_person=si.custom_primary_agent then 'Direct' when si.custom_commission_scheme='Direct Sales Mandate' then 'Downline Margin' else 'Override' end kind
        from `tabSales Team` st join `tabSales Invoice` si on si.name=st.parent and st.parenttype='Sales Invoice'
        where si.name=%(sales_invoice)s and si.docstatus=1 and si.custom_unlisted_shares=1 and coalesce(si.custom_commission_scheme, '') != 'Monthly Incentive' order by st.idx""", f)
    return [AGENT, TIER, col("Commission Type", "kind", "Data"), col("Commission (%)", "percent", "Percent"), col("Commission", "amount")], rows


def my_sales(f):
    rows = sql("""select si.name sales_invoice,si.posting_date,si.customer,
        case when si.custom_primary_agent=st.sales_person then si.base_net_total else 0 end own_sales,
        case when si.custom_primary_agent=st.sales_person then 'Direct' when si.custom_commission_scheme='Direct Sales Mandate' then 'Downline Margin' else 'Override' end kind,
        case when si.custom_commission_scheme='Direct Sales Mandate' then null else st.commission_rate end percent,st.incentives commission """ + BASE + " and st.sales_person=%(sales_person)s order by si.posting_date desc", f)
    return [INVOICE, DATE, col("Customer", "customer", "Link", "Customer"), col("Own Sales", "own_sales"),
            col("Type", "kind", "Data"), col("Commission (%)", "percent", "Percent"), col("Commission", "commission")], rows


def direct_sales(f):
    """One row per Sales Partner and deal: today's deal prices, the partner's quota, and the
    sales and earnings booked under it in the period (Item Price, Direct Sales list)."""
    from supremusangel.unlisted_shares.direct_ladder import DIRECT_SALES_LIST, deal_price_for, partner_access_for
    filters = {"price_list": DIRECT_SALES_LIST, "custom_sales_partner": ["is", "set"]}
    if f.get("sales_person"):
        filters["custom_sales_partner"] = f.sales_person
    if f.get("deal"):
        filters["item_code"] = f.deal
    pairs = {(r.custom_sales_partner, r.item_code) for r in
             frappe.get_all("Item Price", filters=filters, fields=["custom_sales_partner", "item_code"])}
    rows = []
    for partner, deal in sorted(pairs):
        price = deal_price_for(deal) or frappe._dict()
        access = partner_access_for(deal, partner) or frappe._dict()
        booked = sql("""select count(distinct si.name) invoices, coalesce(sum(sii.qty),0) qty,
            coalesce(sum(sii.base_net_amount),0) sales_value
            from `tabSales Invoice` si join `tabSales Invoice Item` sii on sii.parent=si.name
            where si.docstatus=1 and si.custom_is_direct=1 and si.custom_direct_sales_partner=%(partner)s
              and sii.item_code=%(deal)s and si.posting_date between %(from_date)s and %(to_date)s""",
            dict(f, partner=partner, deal=deal))[0]
        earned = flt(sql("""select coalesce(sum(si.custom_direct_sales_partner_earning),0) earned from `tabSales Invoice` si
            where si.docstatus=1 and si.custom_is_direct=1 and si.custom_direct_sales_partner=%(partner)s
              and si.posting_date between %(from_date)s and %(to_date)s
              and exists(select 1 from `tabSales Invoice Item` sii where sii.parent=si.name and sii.item_code=%(deal)s)""",
            dict(f, partner=partner, deal=deal))[0].earned)
        rows.append(frappe._dict(
            sales_partner=partner, deal=deal, rate_row=price.get("name"), valid_from=price.get("valid_from"),
            company_settlement_rate=price.get("price_list_rate"),
            minimum_selling_rate=price.get("custom_minimum_selling_rate"),
            maximum_selling_rate=price.get("custom_maximum_selling_rate"),
            reserved_quantity=access.get("custom_reserved_qty"),
            sold_quantity=frappe.db.get_value("Item Price", access.get("name"), "custom_sold_qty") if access else 0,
            remaining_quantity=frappe.db.get_value("Item Price", access.get("name"), "custom_remaining_qty") if access else 0,
            invoices=booked.invoices, period_qty=booked.qty, sales_value=booked.sales_value,
            agent_earning=earned, company_earning=flt(booked.sales_value) - earned))
    return [
        col("Sales Partner", "sales_partner", "Link", "Sales Person", 180),
        col("Deal", "deal", "Link", "Item", 170), col("Deal Price", "rate_row", "Link", "Item Price", 120),
        col("Price From", "valid_from", "Date"), col("Company Price", "company_settlement_rate"),
        col("Min Selling Rate", "minimum_selling_rate"), col("Max Selling Rate", "maximum_selling_rate"),
        col("Reserved Qty", "reserved_quantity", "Float"), col("Sold Qty", "sold_quantity", "Float"),
        col("Remaining Qty", "remaining_quantity", "Float"), col("Invoices", "invoices", "Int"),
        col("Shares Sold in Period", "period_qty", "Float"), col("Sales Value", "sales_value"),
        col("Company Earning", "company_earning"), col("Agent Earnings (all levels)", "agent_earning"),
    ], rows


def direct_commission(f):
    """Commission earned through Direct Sales (price margins) per agent in the period:
    from their own sales and from sales made below them."""
    extra = ""
    if f.get("sales_person"):
        extra += " and st.sales_person=%(sales_person)s"
    if f.get("sales_partner"):
        extra += " and si.custom_direct_sales_partner=%(sales_partner)s"
    if f.get("deal"):
        extra += " and exists(select 1 from `tabSales Invoice Item` d where d.parent=si.name and d.item_code=%(deal)s)"
    rows = sql("""select st.sales_person, max(st.custom_commission_tier) tier,
        count(distinct si.name) invoices,
        sum(case when st.sales_person=si.custom_primary_agent then
            (select coalesce(sum(i.qty),0) from `tabSales Invoice Item` i where i.parent=si.name) else 0 end) own_qty,
        sum(case when st.sales_person=si.custom_primary_agent then si.base_net_total else 0 end) own_sales,
        sum(case when st.sales_person=si.custom_primary_agent then st.incentives else 0 end) own_margin,
        sum(case when st.sales_person!=si.custom_primary_agent then st.incentives else 0 end) downline_margin,
        sum(st.incentives) total """ + BASE + """ and si.custom_is_direct=1""" + extra + """
        group by st.sales_person order by total desc""", f)
    return [AGENT, TIER, col("Invoices", "invoices", "Int", width=90),
            col("Shares Sold (Own)", "own_qty", "Float", width=130), col("Own Sales Value", "own_sales"),
            col("Own Sale Margin", "own_margin"), col("Downline Margin", "downline_margin"),
            col("Total Direct Commission", "total", width=180)], rows


def my_downline(f):
    tier = frappe.db.get_value("Sales Person", f.sales_person, "custom_tier")
    if not tier or frappe.db.get_value("Commission Tier", tier, "level") == 1:
        frappe.throw("Downline performance is available above Associate level.")
    rows = sql("""select si.custom_primary_agent sales_person, seller.custom_tier tier,
        count(*) transactions,sum(si.base_net_total) business,sum(st.incentives) override_earned
        from `tabSales Invoice` si
        join `tabSales Team` st on st.parent=si.name and st.parenttype='Sales Invoice'
        join `tabSales Person` seller on seller.name=si.custom_primary_agent
        join `tabSales Person` manager on manager.name=%(sales_person)s
        where si.docstatus=1 and si.custom_unlisted_shares=1 and coalesce(si.custom_commission_scheme, '') != 'Monthly Incentive' and st.sales_person=manager.name
        and seller.lft>manager.lft and seller.rgt<manager.rgt
        and si.posting_date between %(from_date)s and %(to_date)s
        group by si.custom_primary_agent,seller.custom_tier order by business desc""", f)
    return [AGENT, TIER, col("Transactions", "transactions", "Int"), col("Business", "business"), col("Your Override", "override_earned")], rows


def my_withdrawals(f):
    rows = sql("""select w.name withdrawal_request,w.posting_date,w.amount,w.workflow_state,w.payment_entry,
        case when pe.docstatus=1 then 'Paid' when pe.docstatus=2 then 'Payment Cancelled'
        when w.docstatus=1 then 'Awaiting Payment' else w.workflow_state end payment_status
        from `tabWithdrawal Request` w left join `tabPayment Entry` pe on pe.name=w.payment_entry
        where w.sales_person=%(sales_person)s and w.posting_date between %(from_date)s and %(to_date)s
        order by w.posting_date desc,w.creation desc""", f)
    return [col("Request", "withdrawal_request", "Link", "Withdrawal Request", 190), DATE, col("Amount", "amount"),
            col("Approval", "workflow_state", "Data"), col("Payment Entry", "payment_entry", "Link", "Payment Entry", 190),
            col("Payment Status", "payment_status", "Data")], rows
