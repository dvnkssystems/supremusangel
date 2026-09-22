import frappe


def create_incentive_data():
	ensure_sales_person_fields()
	_create_merchandise()
	_configure_settings()
	frappe.db.commit()
	print("Done — SA Merchandise and SA Incentive Settings configured.")


def ensure_sales_person_fields():
	"""Custom field linking a Sales Person back to the Customer it was created from
	(via the Create Sales Person button on the Customer form). Idempotent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"Sales Person": [
				{
					"fieldname": "custom_customer",
					"label": "Customer",
					"fieldtype": "Link",
					"options": "Customer",
					"insert_after": "employee",
					"read_only": 1,
					"no_copy": 1,
					"description": "Customer this Sales Person was created from.",
				},
				{
					"fieldname": "custom_incentive_role",
					"label": "Incentive Role",
					"fieldtype": "Data",
					"insert_after": "is_group",
					"read_only": 1,
					"no_copy": 1,
					"description": "RM / TL / BM — derived automatically from the tree position.",
				},
			]
		},
		ignore_validate=True,
	)
	print("  Ensured Sales Person custom fields.")


def _create_merchandise():
	items = [
		{
			"merchandise_name": "Pre-IPO Shares",
			"unit_definition": "1 unit = INR 25,000",
			"unit_value_inr": 25000,
			"is_variable_value": 0,
		},
		{
			"merchandise_name": "MIP Plan for Pre-IPO Shares",
			"unit_definition": "1 unit = plan-specific INR value",
			"unit_value_inr": 0,
			"is_variable_value": 1,
		},
		{
			"merchandise_name": "Fractional Ownership of Franchise",
			"unit_definition": "1 unit = configured franchise fraction/value",
			"unit_value_inr": 0,
			"is_variable_value": 1,
		},
		{
			"merchandise_name": "Neo Green Contract Farming Land",
			"unit_definition": "1 unit = 0.75 land fraction/area unit",
			"unit_value_inr": 0,
			"is_variable_value": 1,
		},
	]

	for item in items:
		if frappe.db.exists("SA Merchandise", item["merchandise_name"]):
			print(f"  Skip (exists): {item['merchandise_name']}")
			continue
		doc = frappe.get_doc({"doctype": "SA Merchandise", **item})
		doc.insert(ignore_permissions=True)
		print(f"  Created merchandise: {item['merchandise_name']}")


def _configure_settings():
	"""Seed the single SA Incentive Settings — base multiples, commission rates,
	and the three slab/band child tables. Idempotent: defaults only fill blanks,
	child tables seed only when empty."""
	s = frappe.get_single("SA Incentive Settings")

	# base & commission defaults — only set when blank, so manual edits survive re-runs
	defaults = {
		"target_multiple": 10,
		"minimum_multiple": 7,
		"team_commission_percent": 1,
		"team_commission_overachieved_percent": 1,
		"team_commission_min_achievement": 70,
		"branch_commission_min_achievement": 70,
		"branch_commission_on_target_percent": 0.5,
		"branch_commission_overachieved_percent": 1,
	}
	for field, value in defaults.items():
		if not s.get(field):
			s.set(field, value)

	if not s.salesperson_slabs:
		# RM (Salesperson) — base target-achievement bonus as incentive_percent (% of salary =
		# 10x the sheet's % of target), plus reward_percent on sales above target. Per the sheet:
		# 70-80% -> 1%, 80-99% -> 2%, 100%+ -> 3% (i.e. incentive 10 / 20 / 30 % of salary).
		for row in [
			{"slab_label": "Below 70%",          "min_achievement": 0,   "max_achievement": 70,  "has_no_upper_limit": 0, "incentive_percent": 0,  "reward_percent": 0},
			{"slab_label": "70% to below 80%",   "min_achievement": 70,  "max_achievement": 80,  "has_no_upper_limit": 0, "incentive_percent": 10, "reward_percent": 0},
			{"slab_label": "80% to below 100%",  "min_achievement": 80,  "max_achievement": 100, "has_no_upper_limit": 0, "incentive_percent": 20, "reward_percent": 0},
			{"slab_label": "100% to below 140%", "min_achievement": 100, "max_achievement": 140, "has_no_upper_limit": 0, "incentive_percent": 30, "reward_percent": 10},
			{"slab_label": "140% to below 200%", "min_achievement": 140, "max_achievement": 200, "has_no_upper_limit": 0, "incentive_percent": 30, "reward_percent": 11},
			{"slab_label": "200% to below 300%", "min_achievement": 200, "max_achievement": 300, "has_no_upper_limit": 0, "incentive_percent": 30, "reward_percent": 12.5},
			{"slab_label": "300% to below 400%", "min_achievement": 300, "max_achievement": 400, "has_no_upper_limit": 0, "incentive_percent": 30, "reward_percent": 14},
			{"slab_label": "400% and above",     "min_achievement": 400, "max_achievement": 0,   "has_no_upper_limit": 1, "incentive_percent": 30, "reward_percent": 15},
		]:
			s.append("salesperson_slabs", row)

	if not s.manager_bonus_slabs:
		for row in [
			{"slab_label": "Below 70%",         "min_achievement": 0,   "max_achievement": 70,  "has_no_upper_limit": 0, "bonus_percent": 0},
			{"slab_label": "70% to below 80%",  "min_achievement": 70,  "max_achievement": 80,  "has_no_upper_limit": 0, "bonus_percent": 1},
			{"slab_label": "80% to below 100%", "min_achievement": 80,  "max_achievement": 100, "has_no_upper_limit": 0, "bonus_percent": 2},
			{"slab_label": "100% and above",    "min_achievement": 100, "max_achievement": 0,   "has_no_upper_limit": 1, "bonus_percent": 3},
		]:
			s.append("manager_bonus_slabs", row)

	if not s.manager_incentive_bands:
		for row in [
			{"slab_label": "100% to below 140%", "from_achievement": 100, "to_achievement": 140, "has_no_upper_limit": 0, "incentive_percent": 10},
			{"slab_label": "140% to below 200%", "from_achievement": 140, "to_achievement": 200, "has_no_upper_limit": 0, "incentive_percent": 11},
			{"slab_label": "200% to below 300%", "from_achievement": 200, "to_achievement": 300, "has_no_upper_limit": 0, "incentive_percent": 12.5},
			{"slab_label": "300% to below 400%", "from_achievement": 300, "to_achievement": 400, "has_no_upper_limit": 0, "incentive_percent": 14},
			{"slab_label": "400% and above",     "from_achievement": 400, "to_achievement": 0,   "has_no_upper_limit": 1, "incentive_percent": 15},
		]:
			s.append("manager_incentive_bands", row)

	s.save(ignore_permissions=True)
	print("  Configured SA Incentive Settings (slabs + commission rates).")
