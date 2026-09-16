# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from supremusangel.telegram_bots.linking import normalize_phone


class TestTelegramLink(FrappeTestCase):
	def test_normalize_phone(self):
		self.assertEqual(normalize_phone("+91 98765-43212"), "9876543212")
		self.assertEqual(normalize_phone("919876543212"), "9876543212")
		self.assertEqual(normalize_phone("09876543212"), "9876543212")
		self.assertIsNone(normalize_phone("12345"))
		self.assertIsNone(normalize_phone(None))
