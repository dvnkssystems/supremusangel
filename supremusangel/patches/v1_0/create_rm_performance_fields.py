# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt
"""Capture points the RM EOD scorecard reads from.

Each field exists purely so an activity can be attributed to one RM and scored
against the WRM minimum-performance standards. Idempotent -- safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	# KPI 1 -- one row per contact, so a day's count survives the next call.
	"Lead": [
		{
			"fieldname": "custom_rm",
			"label": "RM",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "lead_owner",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_contact_log_section",
			"label": "Contact Log",
			"fieldtype": "Section Break",
			"insert_after": "custom_alternate_numbers",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_contact_log",
			"label": "Contact Log",
			"fieldtype": "Table",
			"options": "Lead Contact Log",
			"insert_after": "custom_contact_log_section",
		},
	],
	# KPI 2 and 3 -- Event already carries custom_rm; these split the meeting kinds.
	"Event": [
		{
			"fieldname": "custom_meeting_support",
			"label": "Meeting Support",
			"fieldtype": "Select",
			"options": "\nSelf Hosted\nWith Support",
			"insert_after": "custom_event_mode",
			"description": "Self Hosted means the RM ran it alone. With Support means a senior joined.",
		},
		{
			"fieldname": "custom_venue_type",
			"label": "Venue Type",
			"fieldtype": "Select",
			"options": "\nOffice\nClient Place\nOnline\nOther",
			"insert_after": "custom_meeting_support",
		},
	],
	# KPI 4 -- which RM brought these attendees.
	"Event Booking": [
		{
			"fieldname": "custom_credited_rm",
			"label": "Credited RM",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "user",
			"in_standard_filter": 1,
		}
	],
	# KPI 6 -- recruitment route of team expansion.
	"Job Applicant": [
		{
			"fieldname": "custom_referred_by_rm",
			"label": "Referred By RM",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "source",
			"in_standard_filter": 1,
		}
	],
}

#: KPI 5 counts attendance at team meetings, which Scope Meeting cannot express yet.
SCOPE_MEETING_CATEGORIES = "\nMeetings\nSeminars\nWebinars\nPromotional Activities\nTeam Meeting"


def execute():
	fields = {dt: rows for dt, rows in CUSTOM_FIELDS.items() if frappe.db.exists("DocType", dt)}
	missing = set(CUSTOM_FIELDS) - set(fields)
	if missing:
		# Event Booking / Scope Meeting ship with scope_connect; a site without it
		# still gets every other KPI rather than failing the whole migrate.
		frappe.log_error(
			f"RM Performance: skipped custom fields for absent doctypes {sorted(missing)}",
			"RM Performance patch",
		)
	create_custom_fields(fields, ignore_validate=True)
	add_team_meeting_category()


def add_team_meeting_category():
	"""Scope Meeting belongs to another app, so widen its Select via Property Setter."""
	if not frappe.db.exists("DocType", "Scope Meeting"):
		return
	meta = frappe.get_meta("Scope Meeting")
	field = meta.get_field("category_type")
	if not field:
		return
	if "Team Meeting" in (field.options or ""):
		return
	frappe.make_property_setter(
		{
			"doctype": "Scope Meeting",
			"fieldname": "category_type",
			"property": "options",
			"value": SCOPE_MEETING_CATEGORIES,
			"property_type": "Text",
		},
		is_system_generated=True,
	)
