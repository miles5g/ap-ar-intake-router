# AP/AR Intake Router

**30-second demo**

```bash
python3 -m apar_router
python3 -m unittest discover -s tests -v
```

Prints a triage report and writes balanced dummy-GL journals + bill-control CSV under `output/`. Stdlib Python only.

---

**Portfolio demo** — intake → classify → route → journal pack for multi-entity AP/AR.

Recruiter-safe ops automation pattern. **Not** production software, **not** an ERP connector, **not** trained on real books.

## What it does

1. Ingest synthetic invoices/credits + remittances
2. Classify AP vs AR, entity, urgency, exceptions
3. Route to queues with reason codes
4. Emit a controller-style markdown triage report
5. Write per-entity journals (`GL Code, Debit, Credit, Description`) with payable/receivable balancers
6. Emit a lightweight recurring bill-control summary

## Synthetic-data rules

- Fictional entities (Northwind Retail LLC, Cedar Grove Holdings, …)
- Comic-book people only when needed (Bruce Wayne, not real clients)
- Dummy GLs (`D-####`), whole dollars only
- No real emails, firm names, or employer SOP text

## Quickstart

```bash
git clone https://github.com/miles5g/ap-ar-intake-router.git
cd ap-ar-intake-router
python3 -m apar_router
```

## Status

Runnable. Tests cover routing, journal balance, and scrub guards.

## Author

Miles Johnson — [@miles5g](https://github.com/miles5g)
