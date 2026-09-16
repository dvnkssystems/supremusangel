# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TelegramLink(Document):
	def validate(self):
		duplicate = frappe.db.exists(
			"Telegram Link",
			{
				"telegram_settings": self.telegram_settings,
				"telegram_user_id": self.telegram_user_id,
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(_("This Telegram account is already linked to this bot ({0})").format(duplicate))
