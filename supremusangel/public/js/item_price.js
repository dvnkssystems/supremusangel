// Agents may keep their own downline prices on Item Price (rows are scoped to them by
// unlisted_shares/permissions.py). For an agent, fill in the Agent field on new prices and
// limit the Price List / Item pickers to the Direct Sales list and the deals they sell.
frappe.ui.form.on("Item Price", {
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

frappe.ui.form.on("Item Price", {
	refresh: label_direct_sales_rate,
	price_list: label_direct_sales_rate,
	custom_agent: label_direct_sales_rate,
	custom_sales_partner: label_direct_sales_rate,
});
