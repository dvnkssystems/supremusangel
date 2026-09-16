import frappe


def execute():
	# migrate does not create Module Defs for modules added after install
	if not frappe.db.exists("Module Def", "Telegram Bots"):
		frappe.get_doc(
			{"doctype": "Module Def", "module_name": "Telegram Bots", "app_name": "supremusangel"}
		).insert(ignore_permissions=True)
