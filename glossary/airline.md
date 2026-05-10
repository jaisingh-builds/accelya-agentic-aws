# Airline Vocabulary — Programme Glossary

> These terms appear in every prompt, payload, schema, log line, and review across the next 11 modules.
> Mandatory in `.windsurfrules` REPO RULES; generic terms (`order`, `user`, `item`) are forbidden in payload examples.

## Core 12 (Day 1 Concept 6)

| Term | Definition |
|---|---|
| **PNR** | Passenger Name Record — booking identifier. 6-character alphanumeric (e.g. `6X7Y8Z`). |
| **Airline code** | 2-letter IATA code: AI (Air India), BA (British Airways), EK (Emirates), AA (American Airlines)... |
| **OD** (origin-destination) | Origin–Destination pair: `BOM-DEL`, `LHR-JFK`. In code, the field is `od_pair`. |
| **Fare class** | Single-letter booking class controlling rules and price. Y, B, M, K (economy); J, C, D (business); F, A, P (first). Drives refund eligibility, change fees, mileage accrual. |
| **Fare break** | Point where a fare splits into stop/connecting legs. Used in multi-leg journey pricing. |
| **Offer** | Priced product the GDS returns for a search. Different from a booking — the offer is the quote; the PNR is the commitment. |
| **GDS** | Global Distribution System (e.g. Amadeus, Sabre). The wholesale layer between airlines and travel agents. |
| **Ticket** | Issued document of carriage tied to a PNR. 13-digit numeric with a 3-digit airline prefix (e.g. `098-2400000001`). |
| **Cancellation** | Passenger-initiated termination. Refund eligibility depends on fare rules of the original fare class. |
| **No-show** | Passenger did not board. Impacts refund — usually no refund unless fare class permits. |
| **Remittance** | Agent-to-airline payment owed for ticketed sales. Periodic settlement obligation. |
| **Settlement** | Reconciliation + payment cycle Accelya runs on behalf of airlines. Typically weekly (BSP cycle). |

## Programme schema (locked from Day 4 — lowercase snake_case)

Use these exact field names in code, payloads, and prompts:

```
pnr                — string, 6 chars
airline_code       — string, 2 chars (IATA)
fare_class         — string, 1 char
od_pair            — string, "<3-char>-<3-char>"   (note: NOT `OD`)
settlement_date    — string, ISO 8601 date (YYYY-MM-DD)
ticket_number      — string, "<3>-<10>" (airline prefix + ticket number)
issue_date         — string, ISO 8601 date
fare_amount        — number, decimal
currency           — string, 3-char ISO 4217
agency_iata        — string, 8 chars (IATA agency code)
source_system      — string, e.g. "BSP", "ARC"
bsp_cycle          — string, e.g. "2026-W19" (year + ISO week)
settlement_id      — string, e.g. "BSP-2026-W19-AI234-001"
event_id           — string, UUID
event_type         — string, one of: cancellation, refund, booking, no_show
cancel_reason_code — string, 2 chars (e.g. WX = weather, OP = operational)
```

## Related terms (broader programme — not on slide 14 but appear from Day 4+)

| Term | Definition |
|---|---|
| **BSP** | Billing and Settlement Plan — IATA's global settlement system Accelya operates against. |
| **ARC** | Airlines Reporting Corporation — US equivalent of BSP. |
| **IATA** | International Air Transport Association — the airline industry trade body. |
| **e-ticket** | Electronic ticket — the modern default; "ticket" in this programme always means e-ticket unless stated. |
| **EMD** | Electronic Miscellaneous Document — ancillary services (baggage, seats, etc.). Settlement-relevant but not core to the M1 BR. |
| **PCC** | Pseudo City Code — agent identifier in a GDS. |
| **RBD** | Reservation Booking Designator — the fare class letter (same thing, GDS terminology). |
| **Interline** | A booking involving multiple airlines under a single PNR. |

## Don't use these (forbidden in payload examples)

- `order` / `order_id` — use `pnr` (booking) or `ticket_number` (issued ticket).
- `user` / `user_id` — use `passenger` (display only) or `agency_iata` (commercial identity).
- `item` — use `fare_class` / `coupon` / `service_class` depending on context.
- `transaction_amount` — use `fare_amount` (ticket price) or `amount_local` (settlement).

These generic names hallucinate from Cascade by default. The `.windsurfrules` REPO RULES section bans them; reviewers reject MRs that use them.

---

*Source: Accelya glossary + IATA BSP documentation. Full pre-read pack handed out separately.*
