# AP/AR Intake Router

**Portfolio demo** — ingest synthetic multi-entity invoices and remittances, classify them, and route each document to a queue with a reason code. Then print a markdown triage report **and write a scrubbed journal pack** (dummy GLs, whole dollars).

This is a recruiter-safe recreation of an ops automation pattern (intake → classify → route → journal). It is **not** production software, not connected to an ERP, and not trained on anyone’s books.

## What it shows

1. **Ingest** CSV invoices/credit memos plus JSON remittances for several fictional legal entities
2. **Classify** AP vs AR, resolved entity, urgency, and exception type
3. **Route** to a work queue with a stable reason code
4. **Report** a single markdown triage packet a controller could skim
5. **Journal pack** — per-entity AP/AR CSV exports (`GL Code, Debit, Credit, Description`) with one payable/receivable balancing row
6. **Bill control** — recurring-vendor due-day summary (Acme Widgets, Stark Supplies, plus repeats in the batch)

All names and amounts are invented. Examples: Northwind Retail LLC, Cedar Grove Holdings, Harbor Point Logistics, Maple Street Properties, Blue Ridge Wholesale. People, if mentioned, are comic-book style (Bruce Wayne, not a real client).

## Hard rules

- **Synthetic data only** — no real firm names, client names, invoices, emails, or portfolio figures
- **Dummy GLs only** (`D-####` in `fixtures/coa.json`) — not a real chart of accounts
- **Whole dollars only** in journals (amounts are rounded)
- No secrets, no `.env`, no API keys
- Stdlib Python (3.10+) — no third-party dependencies required
- Demo defaults, not an employer SOP

## Status

Runnable locally. `python -m apar_router` prints the routed triage report **and** writes balanced journals under `output/`.

## Quickstart

```bash
git clone https://github.com/miles5g/ap-ar-intake-router.git
cd ap-ar-intake-router

python3 -m apar_router
```

That command:

1. Prints the markdown triage report to stdout
2. Writes `output/triage_report.md`
3. Writes one balanced CSV per resolved entity + side under `output/journals/`
4. Writes `output/bill_control.csv` and `output/manifest.json`

Useful variants:

```bash
python3 -m apar_router --as-of 2026-09-11 -o output/triage_report.md
python3 -m apar_router --output-dir /tmp/apar-pack
python3 -m unittest discover -s tests -v
```

## Pipeline

```
fixtures/invoices.csv ─┐
                       ├─ ingest ─ classify ─ route ─ markdown report
fixtures/remittances.json ─┘                         │
        ▲                                            ├─ per-entity journal CSVs
fixtures/entities.json                               └─ bill_control.csv
fixtures/coa.json  (dummy GLs)
fixtures/recurring_bills.csv  (Acme Widgets, Stark Supplies)
```

Classification is deterministic rule logic, not a model:

| Signal | How it is decided |
| --- | --- |
| AP vs AR | Document kind (`vendor_invoice` / `credit_memo` → AP; `customer_invoice` / `remittance` → AR) |
| Entity | Hint + aliases (`CGH` → Cedar Grove Holdings). Blank or unknown → `ENTITY_AMBIGUOUS` |
| Exception | First match in priority order: entity → duplicate → unknown counterparty → remittance problems → missing PO → past due |
| Urgency | Days past due, dollar thresholds, and exception class |
| Queue | Critical items escalate; everyone else lands on an AP/AR/entity queue |
| Journal | Resolved-entity invoices/credits only. First invoice number wins (duplicates stay in triage). Remittances stay on the cash-app queues. |

### Queues

| Queue | Typical contents |
| --- | --- |
| `URGENT_ESCALATION` | Critical past-due AR, high-dollar unresolved entity, similar |
| `ENTITY_REVIEW` | Unresolved legal entity |
| `AP_EXCEPTION` | Duplicate invoice, missing PO, unknown vendor, past-due AP |
| `AP_PROCESS` | Clean vendor invoices / credits |
| `AR_UNAPPLIED_CASH` | Short pay, overpay, amount variance, unmatched remittance |
| `AR_CASH_APPLICATION` | Remittance that ties to an open invoice |
| `AR_COLLECTIONS` | Open AR with exceptions (non-critical) |
| `AR_OPEN_ITEMS` | Clean customer invoices awaiting cash |

### Reason codes

`RC-CLEAN-AP`, `RC-CLEAN-AR`, `RC-DUP-INV`, `RC-PO-MISSING`, `RC-AMT-VAR`, `RC-UNKNOWN-CPTY`, `RC-ENTITY-AMBIG`, `RC-REMIT-UNALLOC`, `RC-SHORT-PAY`, `RC-OVERPAY`, `RC-PAST-DUE`, `RC-REMIT-NO-ADVICE`, `RC-ESCALATE`.

### Journal rules

| Rule | Demo behavior |
| --- | --- |
| Columns | `GL Code`, `Debit`, `Credit`, `Description` |
| GLs | Dummy `D-####` codes from `fixtures/coa.json` |
| Amounts | Rounded to whole dollars |
| Description | `mm/dd/yy - vendor/document ref` |
| Signs | Positive activity → Debit; negative (credit memo / AR revenue) → Credit as a positive |
| Balance | One Accounts Payable (`D-2000`) or Accounts Receivable (`D-1200`) row per file; Debit must equal Credit |

## Sample fixtures

The bundled batch is intentionally messy so the report is interesting:

- Clean AP and a matching remittance (`INV-NW-4412` / `RMT-1001`)
- Duplicate freight invoice (`INV-AT-2201` twice) — routed twice, journaled once
- Missing PO, unknown vendor, blank entity hint
- Short pay, overpay, unallocated cash, remittance with no advice
- Alias resolution (`CGH` → Cedar Grove Holdings)
- Severely past-due AR on Maple Street Properties
- Recurring bill-control vendors **Acme Widgets** (15th) and **Stark Supplies** (1st) — not in the intake CSV, so classify → route counts stay the same

Edit `fixtures/` and rerun the module to see routing change.

On the bundled batch (`--as-of 2026-09-11`) the demo routes **25 documents** like this:

| Queue | Count | What you should see |
| --- | ---: | --- |
| `URGENT_ESCALATION` | 2 | Severely past-due AR; high-dollar unknown entity |
| `ENTITY_REVIEW` | 1 | Blank entity hint |
| `AP_EXCEPTION` | 6 | Duplicates, missing PO, unknown vendor, past-due AP |
| `AR_UNAPPLIED_CASH` | 5 | Short pay, overpay, variance, unmatched / no advice |
| `AP_PROCESS` | 5 | Clean vendor invoices and the credit memo |
| `AR_CASH_APPLICATION` | 2 | Remittances that tie to open invoices |
| `AR_OPEN_ITEMS` | 4 | Clean customer invoices still waiting on cash |

## What this is not

- Not OCR, not email intake, not an ERP connector
- Not a collections product and not cash-application software
- Not a claim about any real portfolio, client, or firm
- Thresholds, queues, and dummy GLs are demo defaults, not policy advice

## Project layout

```
apar_router/          # ingest, classify, route, report, journal, bill control
fixtures/             # synthetic entities, invoices, remittances, dummy COA
tests/                # unittest smoke, routing, journal balance, scrub guards
output/               # generated pack (gitignored)
```

## Author

Miles Johnson — [@miles5g](https://github.com/miles5g)
