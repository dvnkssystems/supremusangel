import frappe
from frappe.model.document import Document
from frappe.utils import flt


class DirectSalesRateRevision(Document):
    def before_insert(self):
        # Retired: direct sales rates now live on Item Price (Direct Sales price list).
        frappe.throw("Direct Sales Rate Revision is retired. Add or change direct sales rates on Item Price, "
                     "Direct Sales price list (set Sales Partner and the rates).")

    def validate(self):
        if flt(self.company_settlement_rate) <= 0:
            frappe.throw("Company Settlement Rate must be greater than zero.")
        if flt(self.minimum_selling_rate) <= 0 or flt(self.maximum_selling_rate) <= 0:
            frappe.throw("Selling rate range must be greater than zero.")
        if flt(self.minimum_selling_rate) > flt(self.maximum_selling_rate):
            frappe.throw("Minimum Selling Rate cannot exceed Maximum Selling Rate.")
        if flt(self.company_settlement_rate) > flt(self.minimum_selling_rate):
            frappe.throw("Company Settlement Rate cannot exceed Minimum Selling Rate.")
        mandate = frappe.get_doc("Direct Sales Mandate", self.mandate)
        if mandate.docstatus != 1 or mandate.status == "Cancelled":
            frappe.throw("Rate revisions require an active submitted mandate.")

    def on_submit(self):
        mandate = frappe.get_doc("Direct Sales Mandate", self.mandate)
        mandate.ensure_price_list()
        self.upsert_item_price(mandate)
        self.notify_sales_partner(mandate)

    def upsert_item_price(self, mandate):
        filters = {
            "price_list": mandate.price_list,
            "item_code": mandate.deal,
            "selling": 1,
            "valid_from": self.effective_date,
            # Agents' downline prices share this price list; only touch the base row.
            "custom_agent": ["is", "not set"],
        }
        name = frappe.db.get_value("Item Price", filters, "name")
        values = {
            "doctype": "Item Price",
            "price_list": mandate.price_list,
            "item_code": mandate.deal,
            "selling": 1,
            "currency": frappe.db.get_value("Company", mandate.company, "default_currency"),
            "valid_from": self.effective_date,
            "price_list_rate": self.minimum_selling_rate,
            "uom": frappe.db.get_value("Item", mandate.deal, "stock_uom"),
        }
        if name:
            doc = frappe.get_doc("Item Price", name)
            doc.update(values)
            doc.save(ignore_permissions=True)
        else:
            frappe.get_doc(values).insert(ignore_permissions=True)

    def notify_sales_partner(self, mandate):
        user = frappe.db.get_value("Sales Person", mandate.sales_partner, "custom_agent_user")
        if not user:
            return
        message = (
            f"Direct sales rates for {mandate.deal} are now "
            f"{self.minimum_selling_rate} to {self.maximum_selling_rate}."
        )
        try:
            frappe.get_doc({
                "doctype": "Notification Log",
                "subject": "Direct Sales rates updated",
                "for_user": user,
                "type": "Alert",
                "email_content": message,
                "document_type": self.doctype,
                "document_name": self.name,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Direct Sales rate notification failed")
