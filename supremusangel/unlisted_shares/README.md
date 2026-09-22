# Supremus Angel — Unlisted Shares

Implemented inside the existing `supremusangel` app, in the **Unlisted Shares** module.

## Open the demo

Site: `scope_connect.com`. Local browser alias (same database):
`http://scope-connect.localhost:8000/app/supremus-angel`.

The existing site was backed up before migration. The database backup is
`sites/scope_connect.com/private/backups/20260909_084948-scope_connect_com-database.sql.gz`.

## Business rules

- Deals are non-stock Items in **Unlisted Shares**. Use ISIN as Item Code. Demo identifiers are deliberately fake.
- Agents use the standard Sales Person tree. Set Commission Tier and Agent User on each agent; the user link is unique.
- Customers use the default Sales Person field. An invoice's Primary Agent defaults from its customer.
- Keep share items on a separate invoice from other products. The share flag is derived on the server from Item Group.
- Commission uses **company-currency net invoice value after discounts, before tax** (`base_net_total`).
- Direct sales earn 20%. An Associate sale pays its Sr. Associate 5%, Team Lead 3%, and City Partner 2%.
- A Sr. Associate sale pays its Team Lead 5% and City Partner 3%. A Team Lead sale pays its City Partner 5%.
- Tiers must be consecutive, enabled, and connected through City Partner. Missing tiers, missing parents, invalid percentages and cycles block the invoice with an explanatory error.
- ERPNext contribution percentages must total 100%. The selling agent therefore has 100% contribution and ancestors 0%; **Commission Rate** holds the actual payout percentage, and **Incentives** holds the amount. Commission Tier at Sale is snapshotted on each standard Sales Team row.
- Sales Team on submitted invoices is the only commission ledger. No duplicate referral transaction is created. These invoices are excluded from the older monthly salary incentive engine.
- Submitted splits cannot be edited. Cancel and amend the invoice to correct it. Share credit notes are explicitly blocked; use cancellation/amendment. Cancelled invoice commissions disappear from earned totals; already approved withdrawals remain reserved and may leave a negative available balance until reconciled.

## Approval and withdrawals

Sales Invoice: **Draft → Pending Approval → Approved / Rejected**. Approval submits the invoice and atomically persists its commission rows. Admin can revise rejected documents or cancel approved ones. Ordinary invoices have a separate conditional Submit transition.

This site already has a Payment Entry investor-verification workflow. A thin **Withdrawal Request** preserves that workflow:

1. Agent enters their own Sales Person, company, amount and request date, then requests approval.
2. Admin selects the payee Supplier, bank and payable accounts, plus required site accounting dimensions such as Branch.
3. Approval checks earned commission less all approved requests while locking the agent row, preventing concurrent overdrafts.
4. Approval creates one draft standard **Pay Payment Entry**, linked to the request and agent.
5. An Accounts User submits that entry through the existing payment workflow. The request history then shows Paid. The Admin role by itself does not grant the existing Accounts User workflow action.

Payment party, accounts, company, amount and agent must match the approved request. Requests reserve funds at approval, even before payment. Cancel a submitted payment before cancelling an approved request; an unpaid draft payment is removed automatically when its request is cancelled. Supplier payments are standard accounting entries; this module does not automatically create a commission expense accrual invoice or journal entry.

## Reports and access

Admin reports: Agent-wise Commission Summary; Tier-wise Business Report; Pending Approvals Report; Top Customers by Value; Referral Chain Drill-down.

Agent reports: My Sales and Commission; My Downline Performance; My Withdrawal History. Agent filters are enforced on the server. Admins select a Sales Person to preview these reports. Agent lists and direct document access are scoped as well. Associate users cannot run the downline report.

Tier-wise business counts direct business once, shows earned commission separately, and reports paid amounts from submitted Payment Entries. Paid totals use the agent's current tier; earned totals use the invoice snapshot. Reports group by company where needed. Date filters default to the last three months.

The Supremus Angel workspace includes the required shortcuts, four number cards, weekly transaction value chart, and report links. Existing salary-incentive links remain below the share module. Total Customers counts customers with a default Sales Person, including pre-existing customers.

## Direct Sales price ladder

Ticking **Direct Sales** on a share invoice replaces Tier Commission with a price ladder. When the box is unticked, the direct sales fields are cleared and the invoice uses Tier Commission or Monthly Incentive as before.

**All configuration is on Item Price, in the "Direct Sales" price list.** There are three kinds of row:

| Row | Agent / Sales Partner | Holds |
|---|---|---|
| **Deal price**, one per deal and date | both empty | **Company Price / Share** (the Rate field), Minimum and Maximum Selling Rate, Valid From |
| **Partner access**, one per partner and deal | **Sales Partner** | Reserved Qty (Sold and Remaining are read-only) |
| **Agent price** | **Agent** | Rate = the price this agent charges the people directly under them |

- **The deal price:** the price rules for the deal, and the same for every partner. The latest Valid From in force on the invoice date wins; a later Valid From is a price change, and older rows are the history. The partner buys at the company price.
- **Partner access:** lets the Sales Partner and everyone below them sell the deal. For a sale, the system uses the nearest partner at or above the seller that has access.
- **The quota:** Reserved Qty on the partner access row is the partner's share quota. Sold counts approved Direct Sales invoices for that partner and deal (`custom_direct_sales_partner`). Selling past the quota is blocked.
- **Agent prices:** each agent below the partner buys at their parent's agent-row price. If the parent has none, they pass it on at cost and earn a margin of 0.
- **Margins:** each agent earns (price the next agent down paid, or the invoice rate) − own buy price, multiplied by qty. A missing tier is skipped, so the seller keeps the gap. With settlement 30 and agent prices 32 / 35 / 38, 2 shares sold at 45 split 14 / 6 / 6 / 4.
- **Where earnings are stored:** margins are written to the standard Sales Team `incentives`. The seller has 100% contribution and ancestors 0%, so reports and Withdrawal Requests read them with no extra work. Each invoice records `custom_direct_sales_partner`, `custom_direct_sales_rate` (the deal price row), the company price at the time (`custom_company_settlement_rate`), and `custom_direct_sales_partner_earning`, which is the total across all agents.
- **Price limits:** a customer rate must be between the minimum and maximum selling rate. An agent's price must be between their own buy price and the maximum. Both are checked on save.
- **Price changes:** saving a deal price that is in force lists agent prices that no longer fit. A sale through a stale upline price is blocked until that price is updated.
- **Duplicate check:** `AgentItemPrice` overrides the Item Price class so the duplicate check is scoped by row kind: deal prices per date, each partner's access, each agent's price.
- **Setting agent prices:** agents use the **Direct Sales Prices** button on their Sales Person form, or the Item Price screen. There they see only their own rows (`permissions.item_price_query`), can't touch deal prices, partner access or other agents' rows (`validate_item_price`), and can't delete. The workspace shortcut **Direct Sales Rates** opens the list.
- **Retired:** **Direct Sales Mandate** and **Direct Sales Rate Revision** refuse new records. Existing records were copied once into deal prices, partner access and agent prices (`install.migrate_mandates_to_item_price`). Sites that had the earlier per-partner rate rows are converted by `install.split_rate_rows_into_deal_prices`. Both run once, guarded by site defaults. Their price lists were switched off. Old invoices keep their read-only mandate and revision links.

Code:
- `direct_ladder.py`: chain, pricing, stale-price checks, `AgentItemPrice`, endpoints
- `direct_sales.py`: invoice checks, quota and sold-quantity sync
- `commission_engine.py`: scheme routing and the Sales Team ledger
- `public/js/sales_person.js`: the price dialog
- `public/js/item_price.js`: agent defaults and pickers on Item Price

Tests are in `test_direct_ladder.py` and `test_schemes.py`.

**Running tests.** Always pass `--skip-before-tests --skip-test-records`. Without them, ERPNext's `before_tests` hook runs `delete from tabItem Price` on the site and commits, which wipes every price, including mandate price lists.

```sh
bench --site SITE run-tests --skip-before-tests --skip-test-records --module supremusangel.unlisted_shares.test_direct_ladder
bench --site SITE run-tests --skip-before-tests --skip-test-records --module supremusangel.unlisted_shares.test_schemes
```

## Setup and verification

For the already-installed app:

```sh
bench --site scope_connect.com migrate
bench --site scope_connect.com execute supremusangel.unlisted_shares.demo_data.seed
bench --site scope_connect.com execute supremusangel.unlisted_shares.verification.verify
```

For a separate compatible ERPNext site, install the existing app with `bench --site SITE install-app supremusangel`. Its pre-existing HR/portal integrations and dependencies must also be available. A clean-site installation of the entire pre-existing app has not been tested in this change; the existing demo site's migration and fixture import have been tested.

Metadata and workflows install through versioned DocType JSON, fixtures and idempotent install/migrate hooks. Demo data is **opt-in**, never automatically created on a normal install. Re-running the seeder creates no duplicates and does not rewrite submitted invoices.

Demo data: 4 tiers, 27 agents (1 City Partner, 2 Team Leads, 6 Sr. Associates, 18 Associates), 4 Items, 12 customers, 18 submitted invoices, 2 pending invoices, 3 withdrawal requests and 2 submitted Payment Entries.

Example invoice: `ACC-SINV-2026-00050`, net value ₹25,000; commissions ₹5,000 / ₹1,250 / ₹750 / ₹500.

Synthetic users (no emails sent and no shared password installed):

- `sa.admin@example.test` — Admin
- `sa.associate@example.test` — Agent, Associate 1.1.1
- `sa.teamlead@example.test` — Agent, Arjun Desai

Use your normal administrator process to give these users login access if needed. The recording uses a temporary login link for the synthetic demo account.

Automated acceptance checks cover all eight report endpoints, 18 exact four-row splits, idempotent recalculation, exclusion from legacy incentives, Agent-only access and spoofed filter denial, missing tiers, immutable submitted rows, real cancellation/amendment/resubmission, and overdraft rejection. Mutating acceptance checks use a savepoint and roll back their test changes.

## Manual verification checklist

- [ ] On a separate compatible site, `bench --site SITE install-app supremusangel` runs cleanly.
- [ ] Four Commission Tier records exist with the documented override rules.
- [ ] Sales Person tree expands through City Partner → Team Lead → Sr. Associate → Associate.
- [ ] Approving a new Associate invoice creates four Sales Team rows at 20%, 5%, 3%, 2%.
- [ ] Supremus Angel workspace shortcuts, number cards and weekly chart work.
- [ ] All eight reports return demo data (select an agent for Admin previews).
- [ ] An Agent-only user sees their own permitted data and cannot choose another agent.
- [ ] A withdrawal approval reserves balance and creates a linked draft Payment Entry; Accounts approval shows it as Paid.
- [ ] Watch the narrated screen recording and compare the example invoice split.
