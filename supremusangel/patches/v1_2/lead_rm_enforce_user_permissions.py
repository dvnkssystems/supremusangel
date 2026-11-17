"""Let Employee User Permissions apply through a Lead's RM again.

v1_2.lead_rm_ignore_user_permissions (since removed) set Lead.custom_rm to
ignore user permissions. With Apply Strict User Permissions on, that RM check
is what limits a user with an Employee User Permission to the Leads whose RM is
themselves; without it, everyone crm_extension lets through at Head Quarter
saw every Lead. This puts the check back. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Lead-custom_rm"):
		return

	frappe.db.set_value("Custom Field", "Lead-custom_rm", "ignore_user_permissions", 0)
	frappe.clear_cache(doctype="Lead")
