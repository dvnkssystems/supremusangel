import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class CommissionTier(Document):
    def validate(self):
        if not 1 <= cint(self.level) <= 4 or not all(
            0 <= flt(rate) <= 100
            for rate in (self.own_commission_percent, self.direct_sale_commission_percent)
        ):
            frappe.throw("Level must be 1–4 and commission percentages must be 0–100%.")
        seen = set()
        for row in self.overrides:
            origin = frappe.db.get_value("Commission Tier", row.from_tier, "level")
            if row.from_tier in seen or not origin or cint(origin) >= cint(self.level) or not 0 <= flt(row.percent) <= 100:
                frappe.throw("Each override must reference a unique lower tier with a percentage of 0–100.")
            seen.add(row.from_tier)
