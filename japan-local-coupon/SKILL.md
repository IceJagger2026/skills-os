---
name: japan-local-coupon
description: Find currently valid Japanese coupons and campaigns with source-backed validity checks. Use when the user asks for Japan coupons, Apple Gift Card campaigns, Apple Store gift card offers, Amazon Japan deals, PayPay cashback/coupons, payment campaigns, supermarket/drugstore coupons, high-value convenience store coupons, or a daily local coupon brief in Chinese or Japanese.
---

# Japan Local Coupon

## Purpose

Find currently valid coupons and campaigns in Japan, especially Apple Gift Card / Apple Store gift card campaigns, Amazon Japan campaigns, PayPay campaigns, other payment campaigns, and local daily-use offers.

## Core Rules

- Use official campaign pages and existing coupon/campaign sites.
- Do not rely on generic search-engine snippets as coupon proof.
- Only include coupons and campaigns that are currently valid on the request date.
- Exclude expired coupons.
- Exclude coupons with unclear validity, unclear redemption period, or missing conditions.
- Never invent discount amounts, dates, inventory status, or conditions.
- Always include source URL and validity period.
- Prefer offers that are easy to use today.
- Use web search when the user asks for current coupons, daily coupons, latest campaigns, or anything date-sensitive.

## Ranking Preference

Apple Gift Card / Apple Store gift card campaigns, Amazon Japan campaigns, and PayPay campaigns have the highest priority.

Convenience store coupons have low priority. Include 7-Eleven, FamilyMart, Lawson, or Ministop only when the offer is clearly high-value, such as:

- free item / free redemption ticket
- buy-one-get-one
- clear discount coupon
- useful daily item discount
- valid today with clear conditions

## Priority Sources

1. Official campaign pages:
   Apple, Apple Gift Card retailers, Amazon Japan, PayPay, Rakuten Pay, d-barai, au PAY, AEON Pay, supermarket/drugstore official campaigns, 7-Eleven, FamilyMart, Lawson, Ministop.
2. Coupon/campaign aggregation sites:
   Japanese coupon and campaign aggregation sites may be used for discovery and secondary confirmation.
3. Search engines:
   Use only to discover source pages. Do not use snippets as proof.

## Priority Categories

1. Apple Gift Card / Apple Store gift card campaigns
2. Amazon Japan gift card, coupon, point-up, time-sale, Smile Sale, Prime, and Amazon Pay campaigns
3. PayPay cashback, coupon, local government, gourmet, Apple Gift Card, and Amazon-related campaigns
4. Rakuten Pay / d-barai / au PAY / AEON Pay campaigns
5. Supermarket and drugstore coupons
6. Local restaurant coupons
7. High-value convenience store coupons only

## Validity Checks

Before recommending a coupon or campaign, check:

- start date
- end date
- coupon issue period
- redemption period
- app/account requirement
- whether the coupon may be personalized
- whether the offer may end early because stock or planned quantity runs out

If the request date is after the end date, exclude it.

If validity is unclear, do not include it in the main list. Put it in a short "unclear / skipped" note only when useful.

## Workflow

1. Resolve the request date, location, radius, and focus categories. Use `config/user_config.json` defaults when the user does not specify them.
2. Search official campaign pages first, then aggregation sites.
3. Open source pages and verify validity details from page content, not snippets.
4. Rank offers by category priority, immediate usefulness, certainty, value, and ease of redemption.
5. Return only source-backed coupons/campaigns that are valid on the request date.

Use `prompts/daily_coupon_prompt.md` as the reusable daily request template when the user wants a daily coupon run.

## Output Format

Return coupons/campaigns grouped by:

1. Today's best
2. Apple Gift Card / Apple Store gift cards
3. Amazon Japan
4. PayPay campaigns
5. Other payment / points campaigns
6. Supermarket / drugstore / local offers
7. High-value convenience store offers

For every coupon/campaign, include:

- title
- store/company
- category
- benefit
- valid period
- coupon issue period, if different
- redemption period, if different
- how to use
- app/account requirement
- source URL
- official verification URL, if available
- confidence: high / medium
- warning notes, if any

Default output language: Chinese. Keep Japanese coupon names unchanged.
