# Copyright (c) 2026, Aniket Shinde and contributors
# For license information, please see license.txt

import calendar
from datetime import date

import frappe
from frappe.model.document import Document
from frappe.utils import flt
from supremusangel.unlisted_shares.schemes import require_monthly_agent, uses_tier_commission

from supremusangel.supremus_angel.incentive_source import (
	get_group_commission,
	get_member_target,
	get_sales_rows,
	get_settings,
)


class SATLIncentiveCalculation(Document):
	def before_save(self):
		if self.calculation_month and not self.from_date:
			self._set_date_range()

	@frappe.whitelist()
	def calculate(self):
		require_monthly_agent(self.team_lead)
		if not self.salary:
			frappe.throw(frappe._("Please enter the TL monthly salary before calculating."))
		if not self.calculation_month:
			frappe.throw(frappe._("Please enter a calculation month (YYYY-MM)."))
		if not self.team_lead:
			frappe.throw(frappe._("Please select a team lead (Sales Person)."))

		self._set_date_range()

		settings = get_settings()
		self._calculate_personal(settings)
		self._calculate_team(settings)

		self.total_payout = flt(self.personal_payout) + flt(self.team_commission_amount)
		self.status = "Calculated"
		self.save()

	# ------------------------------------------------------------------ personal

	def _calculate_personal(self, settings):
		salary = flt(self.salary)
		personal_target = salary * flt(settings.target_multiple)
		self.personal_target = personal_target
		self.minimum_target = salary * flt(settings.minimum_multiple)

		records = self._get_sales_records(self.team_lead)
		personal_sales = sum(flt(r.credited_amount) for r in records)
		self.personal_sales = personal_sales
		self.personal_achievement_percent = (
			(personal_sales / personal_target * 100) if personal_target else 0
		)

		# Base Target Achievement Bonus — flat % of personal target by slab.
		bonus_slab = self._get_bonus_slab(settings, self.personal_achievement_percent)
		if bonus_slab:
			self.bonus_slab = bonus_slab.slab_label
			self.bonus_percent = flt(bonus_slab.bonus_percent)
		else:
			self.bonus_slab = None
			self.bonus_percent = 0
		self.bonus_amount = personal_target * (flt(self.bonus_percent) / 100)

		# Personal incentive — marginal across bands on sales above target.
		self.personal_incentive_amount = self._marginal_incentive(settings, personal_sales, personal_target)

		self.personal_payout = flt(self.bonus_amount) + flt(self.personal_incentive_amount)

		self.set("personal_sales_details", [])
		for r in records:
			self.append(
				"personal_sales_details",
				{
					"sales_invoice": r.sales_invoice,
					"posting_date": r.posting_date,
					"customer": r.customer,
					"allocated_percentage": r.allocated_percentage,
					"total_sales_value": r.credited_amount,
				},
			)

	def _marginal_incentive(self, settings, personal_sales, personal_target):
		"""Sum incentive over each band, applying the band rate only to the
		portion of personal_sales that falls inside that band. Bands are defined
		as % of personal_target (100 => 10x)."""
		if not personal_target or personal_sales <= personal_target:
			return 0

		bands = sorted(
			settings.manager_incentive_bands, key=lambda b: flt(b.from_achievement)
		)

		total = 0.0
		for band in bands:
			lower = personal_target * flt(band.from_achievement) / 100
			if band.has_no_upper_limit or not band.to_achievement:
				upper = personal_sales
			else:
				upper = personal_target * flt(band.to_achievement) / 100
			portion = min(personal_sales, upper) - lower
			if portion > 0:
				total += portion * (flt(band.incentive_percent) / 100)
		return total

	def _get_bonus_slab(self, settings, achievement_percent):
		slabs = sorted(
			settings.manager_bonus_slabs, key=lambda s: flt(s.min_achievement), reverse=True
		)
		for slab in slabs:
			if flt(achievement_percent) < flt(slab.min_achievement):
				continue
			if slab.has_no_upper_limit or flt(achievement_percent) < flt(slab.max_achievement):
				return slab
		return None

	# --------------------------------------------------------------------- team

	def _calculate_team(self, settings):
		members = self._get_team_members()
		self.set("team_details", [])

		full_team_target = 0.0
		team_sales = 0.0
		no_target = []

		for member in members:
			member_sales = sum(
				flt(r.credited_amount) for r in self._get_sales_records(member)
			)
			team_sales += member_sales

			# Falls back to salary x target_multiple when the member has no calc
			# yet, so the team target never silently collapses to 0.
			member_target, member_salary, has_calc = get_member_target(
				member, self.calculation_month, settings
			)
			if not member_target:
				no_target.append(member)

			full_team_target += member_target

			self.append(
				"team_details",
				{
					"member": member,
					"member_salary": member_salary,
					"member_target": member_target,
					"member_sales": member_sales,
					"member_achievement_percent": (
						(member_sales / member_target * 100) if member_target else 0
					),
					"has_calculation": has_calc,
				},
			)

		min_achievement = flt(settings.team_commission_min_achievement)

		self.team_member_count = len(members)
		self.full_team_target = full_team_target
		self.team_target = full_team_target * (min_achievement / 100)
		self.team_sales = team_sales

		amount, rate, achievement = get_group_commission(
			full_team_target,
			team_sales,
			min_achievement,
			settings.team_commission_percent,
			settings.team_commission_overachieved_percent,
		)
		self.team_achievement_percent = achievement
		self.team_commission_percent = rate
		self.team_commission_amount = amount

		if no_target:
			frappe.msgprint(
				frappe._(
					"No salary could be resolved for {0} for {1}; their sales were counted but "
					"their target could not be included in the team target. Assign a Salary "
					"Structure or calculate their incentive first for an accurate team target."
				).format(", ".join(no_target), self.calculation_month),
				indicator="orange",
				title=frappe._("Team Target Incomplete"),
			)

	def _get_team_members(self):
		"""Everyone in the team lead's subtree (the 'whole team'), excluding the
		team lead themselves.

		Group nodes are included, not skipped -- each person in the tree counts
		once, whatever their scheme. A TL normally has only salespeople beneath
		them, but keeping this identical to the branch rule means a mis-shaped
		tree can never silently drop people from the team target."""
		tl = frappe.db.get_value("Sales Person", self.team_lead, ["lft", "rgt"], as_dict=True)
		if not tl:
			return []
		members = frappe.get_all(
			"Sales Person",
			filters={"lft": [">", tl.lft], "rgt": ["<", tl.rgt]},
			pluck="name",
		)
		return [member for member in members if not uses_tier_commission(member)]

	# -------------------------------------------------------------------- shared

	def _get_sales_records(self, sales_person):
		return get_sales_rows(sales_person, self.from_date, self.to_date)

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
