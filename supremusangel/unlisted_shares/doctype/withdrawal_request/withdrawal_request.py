import frappe
from frappe.model.document import Document
from frappe.utils import flt
from supremusangel.unlisted_shares.permissions import is_admin, linked_agent


class WithdrawalRequest(Document):
    def validate(self):
        if not is_admin() and self.sales_person != linked_agent():
            frappe.throw("You can request only your own commission.", frappe.PermissionError)
        if flt(self.amount) <= 0:
            frappe.throw("Withdrawal amount must be positive.")
        if not frappe.db.get_value("Sales Person", self.sales_person, "custom_tier"):
            frappe.throw("Select an agent with a Commission Tier.")

    def before_submit(self):
        if not is_admin():
            frappe.throw("Only an Admin can approve withdrawals.", frappe.PermissionError)
        # Serialize approvals for this agent, including simultaneous requests.
        frappe.db.sql("select name from `tabSales Person` where name=%s for update", self.sales_person)
        earned = frappe.db.sql("""select coalesce(sum(st.incentives),0) from `tabSales Team` st
            join `tabSales Invoice` si on si.name=st.parent and st.parenttype='Sales Invoice'
            where si.docstatus=1 and si.custom_unlisted_shares=1 and coalesce(si.custom_commission_scheme, '') != 'Monthly Incentive' and si.company=%s and st.sales_person=%s""",
            (self.company, self.sales_person))[0][0]
        reserved = frappe.db.sql("""select coalesce(sum(amount),0) from `tabWithdrawal Request`
            where docstatus=1 and company=%s and sales_person=%s and name!=%s""",
            (self.company, self.sales_person, self.name))[0][0]
        if flt(self.amount) > flt(earned) - flt(reserved):
            frappe.throw(f"Insufficient commission balance. Available: {flt(earned)-flt(reserved):,.2f}.")
        if not all((self.supplier, self.paid_from, self.paid_to)):
            frappe.throw("Admin must set the payee Supplier, Bank Account and Payable Account before approval.")

    def on_submit(self):
        # Approval reserves commission and creates a draft standard Pay entry.
        # Accounts submits it through the site's existing payment verification.
        if self.payment_entry:
            return
        currency = frappe.db.get_value("Company", self.company, "default_currency")
        pe = frappe.get_doc(dict(doctype="Payment Entry", payment_type="Pay", company=self.company,
            posting_date=self.posting_date, party_type="Supplier", party=self.supplier,
            paid_from=self.paid_from, paid_to=self.paid_to, paid_from_account_currency=currency,
            paid_to_account_currency=currency, paid_amount=self.amount, received_amount=self.amount,
            source_exchange_rate=1, target_exchange_rate=1, reference_no=self.name, reference_date=self.posting_date,
            custom_sales_person=self.sales_person, custom_withdrawal_request=self.name))
        from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
        for dimension in get_accounting_dimensions():
            pe.set(dimension, self.get(dimension))
        pe.insert(ignore_permissions=True)
        self.db_set("payment_entry", pe.name)

    def before_cancel(self):
        if not self.payment_entry:
            return
        status = frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus")
        if status == 1:
            frappe.throw("Cancel the submitted Payment Entry before cancelling this withdrawal.")
        if status == 0:
            draft_payment = self.payment_entry
            self.db_set("payment_entry", None)
            frappe.delete_doc("Payment Entry", draft_payment, ignore_permissions=True)
