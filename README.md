**[Open the demo](https://miles5g.github.io/ap-ar-intake-router/)**

Sorts a pile of incoming invoices, credit memos, and payments across several companies: decides what each one is, who it belongs to, whether something is wrong, and which queue it goes to. Then writes the journals.

# AP/AR Intake Router

This is a public rebuild of the workflow pattern on sample data. This GitHub version was not deployed or used at any employer.

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
4. **Review.** The tool flags items, and a person approves or edits them before anything is final. The web demo waits for that review. The command writes the draft pack.
5. **Report.** Prints a triage report: what is in each queue, dollar totals, and which items are flagged.
6. **Journal.** Writes one balanced journal per company, plus a recurring bill tracker. The journals are a draft until that review is done.

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
