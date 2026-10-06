# AP/AR Intake Router

Sorts a pile of incoming invoices, credit memos, and payments across several companies: decides what each one is, who it belongs to, whether something is wrong, and which queue it goes to. Then writes the journals.

This is a rebuild of an intake workflow I run at work, on fake data so it can be public.

## Run it (30 seconds)

```bash
git clone https://github.com/miles5g/ap-ar-intake-router.git
cd ap-ar-intake-router
python3 -m apar_router
```

Python 3.10+. Nothing to install. On Windows use `py -m apar_router`.

Want each step explained as it runs? `python3 -m apar_router --walkthrough`

## What happens

1. **Ingest.** Loads 25 fake documents: invoices, credit memos, and payment records.
2. **Classify.** Bill we owe (AP) or money owed to us (AR)? Which company? Anything off, like a duplicate invoice, a missing PO, or a past due date?
3. **Route.** Sends each document to a queue (urgent, exception, normal processing, cash to apply) with a short reason.
4. **Report.** Prints a triage report: what is in each queue, dollar totals, and what needs a person.
5. **Journal.** Writes one balanced journal per company, plus a recurring bill tracker.

## What you get

```
| Queue                | Count | Face value  |
| URGENT_ESCALATION    |     2 | $40,500.00  |
| AP_EXCEPTION         |     6 | $24,435.00  |
| AR_UNAPPLIED_CASH    |     5 | $34,000.00  |
| AP_PROCESS           |     5 | $48,480.00  |
```

Files land in `output/`.

## Tests

```bash
python3 -m unittest discover -s tests
```

Covers routing rules, balanced journals, and a check that no real names are in the repo.

## Data

All fake: made-up companies, round dollar amounts, dummy account codes.
