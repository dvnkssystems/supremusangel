"""Stop Employee User Permissions from deciding who sees a Lead through its RM.

Lead.custom_rm (see v1_0.create_rm_performance_fields) is there to attribute a
lead to an RM. As a plain Employee link it also picked up every employee's
own-record User Permission, and with strict user permissions on, a user saw only
the Leads whose RM was themselves: one given to them with anyone else's RM, or
none, was missing from their Telecalling Desk and refused to open ("linked to
Employee ... in field RM").

Who may see a Lead is crm_extension's lead permission rules; Lead.custom_branch
already ignores user permissions for the same reason. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Lead-custom_rm"):
		return

	frappe.db.set_value("Custom Field", "Lead-custom_rm", "ignore_user_permissions", 1)
	frappe.clear_cache(doctype="Lead")
