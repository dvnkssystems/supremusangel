# Copyright (c) 2026, Aniket Shinde and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from supremusangel.supremus_angel.api.policy_ack import acknowledge_policies, get_pending_policies

POLICY = "_TEST-POLICY-ACK"
BROWSER = "Test Browser"


class TestCompanyPolicyAcknowledgement(FrappeTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": "Company Policy",
				"policy_code": POLICY,
				"policy_title": POLICY,
				"active": 1,
				"mandatory_for_new_joinee": 1,
			}
		).insert(ignore_permissions=True)

		# Serve as a request, on the 1 in 10 links Frappe samples for its link count.
		frappe.local.request = SimpleNamespace(headers={"User-Agent": BROWSER})
		self.addCleanup(self.leave_request)
		for patcher in (
			patch("frappe.model.utils.link_count.random", return_value=0.95),
			patch.object(frappe.db, "commit"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def leave_request(self):
		frappe.local.request = None
		if hasattr(frappe.local, "_link_count"):
			del frappe.local._link_count
		frappe.set_user("Administrator")

	def make_user(self, email):
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Policy",
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
		return email

	def make_employee(self, user):
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Policy",
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2026-01-01",
					"status": "Active",
					"company": frappe.get_all("Company", pluck="name", limit=1)[0],
					"user_id": user,
				}
			)
			.insert(ignore_permissions=True, ignore_mandatory=True)
			.name
		)

	def acknowledge_as(self, user):
		frappe.set_user(user)
		acknowledge_policies(f'["{POLICY}"]')
		return frappe.get_all(
			"Company Policy Acknowledgement", {"user": user, "policy": POLICY}, ["name", "employee"]
		)

	def assert_not_pending(self):
		self.assertNotIn(POLICY, [policy.name for policy in get_pending_policies()])

	def test_employee_acknowledges_when_the_link_is_sampled(self):
		user = self.make_user("policy.ack.employee@example.com")
		employee = self.make_employee(user)

		frappe.set_user(user)
		self.assertIn(POLICY, [policy.name for policy in get_pending_policies()])

		rows = self.acknowledge_as(user)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].employee, employee)
		self.assertEqual(rows[0].name, f"{employee}-{POLICY}")
		self.assert_not_pending()

	def test_two_users_without_an_employee_both_acknowledge(self):
		for email in ("policy.ack.a@example.com", "policy.ack.b@example.com"):
			user = self.make_user(email)

			self.assertEqual(len(self.acknowledge_as(user)), 1)
			self.assert_not_pending()

	def test_a_long_browser_string_does_not_block_acknowledging(self):
		user = self.make_user("policy.ack.phone@example.com")
		frappe.local.request.headers["User-Agent"] = "x" * 145

		rows = self.acknowledge_as(user)

		self.assertEqual(len(rows), 1)
		saved = frappe.db.get_value("Company Policy Acknowledgement", rows[0].name, "user_agent")
		self.assertEqual(saved, "x" * 140)
		self.assert_not_pending()

	def test_acknowledging_twice_keeps_one_row(self):
		user = self.make_user("policy.ack.twice@example.com")
		self.acknowledge_as(user)

		self.assertEqual(len(self.acknowledge_as(user)), 1)
