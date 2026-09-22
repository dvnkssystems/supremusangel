import frappe
from frappe.model.document import Document
from frappe.utils import flt


class DirectSalesMandate(Document):
    def before_insert(self):
        # Retired: direct sales rates now live on Item Price (Direct Sales price list).
        frappe.throw("Direct Sales Mandate is retired. Add or change direct sales rates on Item Price, "
                     "Direct Sales price list (set Sales Partner and the rates).")

    def validate(self):
        if flt(self.reserved_quantity) <= 0:
            frappe.throw("Reserved Quantity must be greater than zero.")
        if self.deal and frappe.db.get_value("Item", self.deal, "item_group") != "Unlisted Shares":
            frappe.throw("Direct Sales Mandate deal must be an Unlisted Shares item.")
        if self.sales_partner and not frappe.db.get_value("Sales Person", self.sales_partner, "enabled"):
            frappe.throw("Sales Partner must be an enabled Sales Person.")
        self.sold_quantity = self.sold_quantity or 0
        self.remaining_quantity = flt(self.reserved_quantity) - flt(self.sold_quantity)
        if self.remaining_quantity < 0:
            frappe.throw("Sold Quantity cannot exceed Reserved Quantity.")
        if self.docstatus == 0:
            self.status = "Draft"

    def on_submit(self):
        self.status = "Active"
        self.remaining_quantity = flt(self.reserved_quantity) - flt(self.sold_quantity)
        self.ensure_price_list()
        frappe.db.set_value(self.doctype, self.name, {
            "status": self.status,
            "remaining_quantity": self.remaining_quantity,
            "price_list": self.price_list,
        })

    def before_cancel(self):
        if frappe.db.exists("Sales Invoice", {"custom_direct_sales_mandate": self.name, "docstatus": 1}):
            frappe.throw("Cannot cancel a mandate with submitted Sales Invoices.")

    def on_cancel(self):
        self.db_set("status", "Cancelled")

    def ensure_price_list(self):
        if self.price_list:
            return self.price_list
        price_list = f"{self.sales_partner} - {self.deal} - Direct Sales"
        if not frappe.db.exists("Price List", price_list):
            frappe.get_doc({
                "doctype": "Price List",
                "price_list_name": price_list,
                "selling": 1,
                "enabled": 1,
                "currency": frappe.db.get_value("Company", self.company, "default_currency"),
            }).insert(ignore_permissions=True)
        self.price_list = price_list
        if self.name and self.docstatus == 1:
            self.db_set("price_list", price_list)
        return price_list
