import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Employee": [
				{
					"fieldname": "custom_checklist_completed_on",
					"label": "Onboarding Checklist Completed On",
					"fieldtype": "Datetime",
					"insert_after": "custom_onboarding_completed",
					"read_only": 1,
					"no_copy": 1,
					"module": "Telegram Bots",
				}
			]
		},
		update=True,
	)
