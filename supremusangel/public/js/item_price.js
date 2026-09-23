// Agents may keep their own downline prices on Item Price (rows are scoped to them by
// unlisted_shares/permissions.py). For an agent, fill in the Agent field on new prices and
// limit the Price List / Item pickers to the Direct Sales list and the deals they sell.
frappe.ui.form.on("Item Price", {
	setup(frm) {
		// Only agents (Sales Persons with a Commission Tier) take part in Direct Sales, and deals
		// are handed out to City Partners, who sell them down their own tree.
		frm.set_query("custom_agent", () => ({ filters: { custom_tier: ["is", "set"], enabled: 1 } }));
		frm.set_query("custom_sales_partner", () => ({ filters: { custom_tier: "City Partner", enabled: 1 } }));
	},
	onload(frm) {
		frappe.call({
			method: "supremusangel.unlisted_shares.direct_ladder.get_item_price_context",
			callback(r) {
				const ctx = r.message || {};
				if (!ctx.agent) return;
				frm._agent_ctx = ctx;
				if (frm.is_new() && !frm.doc.custom_agent) frm.set_value("custom_agent", ctx.agent);
				frm.set_df_property("custom_agent", "read_only", 1);
				frm.set_query("price_list", () => ({ filters: { name: ["in", ctx.price_lists] } }));
				frm.set_query("item_code", () => ({ filters: { name: ["in", ctx.deals] } }));
			},
		});
	},
});

// In the Direct Sales list, Rate means something different on each kind of row: the deal's
// company price, an agent's downline price, or nothing (partner access carries only a quota).
function label_direct_sales_rate(frm) {
	const direct = frm.doc.price_list === "Direct Sales";
	const partner = direct && frm.doc.custom_sales_partner;
	const label = !direct ? __("Rate") : frm.doc.custom_agent ? __("Downline Price") : partner ? __("Rate") : __("Company Price / Share");
	frm.set_df_property("price_list_rate", "label", label);
	frm.set_df_property("price_list_rate", "hidden", partner ? 1 : 0);
	frm.set_df_property("price_list_rate", "reqd", partner ? 0 : 1);
	if (partner && frm.doc.price_list_rate) frm.set_value("price_list_rate", 0);
}

// A partner access row has no rate of its own: the partner buys at the deal's Company Price.
// Show that price, read live from the deal price in force, so admins can see it here.
function show_partner_rate(frm) {
	frm.set_intro("");
	if (frm.doc.price_list !== "Direct Sales" || !frm.doc.custom_sales_partner || !frm.doc.item_code) return;
	frappe
		.call("supremusangel.unlisted_shares.direct_ladder.get_deal_price", { item_code: frm.doc.item_code })
		.then(({ message: p }) => {
			if (!p) {
				frm.set_intro(__("This deal has no price yet. Add the deal price first (Direct Sales, no Agent or Sales Partner)."), "red");
				return;
			}
			frm.set_intro(
				__("{0} buys at {1} per share: the deal's Company Price in force since {2}. Customers pay {3} to {4}.", [
					frappe.utils.escape_html(frm.doc.custom_sales_partner),
					format_currency(p.company_price),
					frappe.datetime.str_to_user(p.valid_from),
					format_currency(p.minimum_selling_rate),
					format_currency(p.maximum_selling_rate),
				]),
				"blue"
			);
		});
}

frappe.ui.form.on("Item Price", {
	refresh(frm) {
		label_direct_sales_rate(frm);
		show_partner_rate(frm);
	},
	item_code: show_partner_rate,
	price_list: label_direct_sales_rate,
	custom_agent: label_direct_sales_rate,
	custom_sales_partner(frm) {
		label_direct_sales_rate(frm);
		show_partner_rate(frm);
	},
});
