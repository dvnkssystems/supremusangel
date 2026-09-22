# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

import calendar
from datetime import date

import frappe
from frappe.model.document import Document
from frappe.utils import flt
from supremusangel.unlisted_shares.schemes import require_monthly_agent

from supremusangel.supremus_angel.incentive_source import get_sales_rows, get_settings


class SAIncentiveCalculation(Document):
	def before_save(self):
		if self.calculation_month and not self.from_date:
			self._set_date_range()

	@frappe.whitelist()
	def calculate(self):
		require_monthly_agent(self.sales_person)
		if not self.salary:
			frappe.throw(frappe._("Please enter the monthly salary before calculating."))
		if not self.calculation_month:
			frappe.throw(frappe._("Please enter a calculation month (YYYY-MM)."))
		if not self.sales_person:
			frappe.throw(frappe._("Please select a sales person."))

		settings = get_settings()
		salary = flt(self.salary)
		base_target = salary * flt(settings.target_multiple)
		minimum_target = salary * flt(settings.minimum_multiple)

		self.base_target = base_target
		self.minimum_target = minimum_target

		self._set_date_range()

		records = get_sales_rows(self.sales_person, self.from_date, self.to_date)

		total_sales = sum(flt(r.credited_amount) for r in records)
		self.total_sales = total_sales
		self.achievement_percent = (total_sales / base_target * 100) if base_target else 0

		slab = self._get_applicable_slab(settings, self.achievement_percent)
		if slab:
			self.slab_applied = slab.slab_label
			self.incentive_percent = flt(slab.incentive_percent)
			self.reward_percent = flt(slab.reward_percent)
		else:
			self.slab_applied = None
			self.incentive_percent = 0
			self.reward_percent = 0

		self.incentive_amount = salary * (self.incentive_percent / 100)
		self.reward_amount = (
			(total_sales - base_target) * (self.reward_percent / 100)
			if total_sales > base_target
			else 0
		)
		self.total_payout = self.incentive_amount + self.reward_amount

		self.set("sales_details", [])
		for r in records:
			self.append(
				"sales_details",
				{
					"sales_invoice": r.sales_invoice,
					"posting_date": r.posting_date,
					"customer": r.customer,
					"allocated_percentage": r.allocated_percentage,
					"total_sales_value": r.credited_amount,
				},
			)

		self.status = "Calculated"
		self.save()

	def _set_date_range(self):
		if not self.calculation_month or len(self.calculation_month) < 7:
			return
		try:
			year = int(self.calculation_month[:4])
			month = int(self.calculation_month[5:7])
			self.from_date = date(year, month, 1).strftime("%Y-%m-%d")
			last_day = calendar.monthrange(year, month)[1]
			self.to_date = date(year, month, last_day).strftime("%Y-%m-%d")
		except (ValueError, IndexError):
			frappe.throw(frappe._("Invalid calculation month format. Use YYYY-MM."))

	def _get_applicable_slab(self, settings, achievement_percent):
		slabs = sorted(
			settings.salesperson_slabs, key=lambda s: flt(s.min_achievement), reverse=True
		)
		for slab in slabs:
			if flt(achievement_percent) < flt(slab.min_achievement):
				continue
			if slab.has_no_upper_limit or flt(achievement_percent) < flt(slab.max_achievement):
				return slab
		return None
