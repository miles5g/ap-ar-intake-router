/* Browser port of apar_router: ingest, classify, route, report, journals. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.AparPipeline = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var FORBIDDEN_TOKENS = [
    "gursey",
    "kpmg",
    "deloitte",
    "ey.com",
    "pwc",
    "pricewaterhouse",
    "ernst & young",
    "grant thornton",
    "@gmail.com",
    "@yahoo.com",
    "@outlook.com",
    "@hotmail.com",
  ];

  var QUEUE_ORDER = [
    "URGENT_ESCALATION",
    "ENTITY_REVIEW",
    "AP_EXCEPTION",
    "AR_UNAPPLIED_CASH",
    "AR_COLLECTIONS",
    "AP_PROCESS",
    "AR_CASH_APPLICATION",
    "AR_OPEN_ITEMS",
  ];

  var EXCEPTION_PRIORITY = [
    "ENTITY_AMBIGUOUS",
    "DUPLICATE_INVOICE",
    "UNKNOWN_COUNTERPARTY",
    "UNALLOCATED_REMITTANCE",
    "MISSING_REMIT_ADVICE",
    "SHORT_PAY",
    "OVERPAYMENT",
    "AMOUNT_VARIANCE",
    "MISSING_PO",
    "PAST_DUE",
    "NONE",
  ];

  var REASON_CODES = {
    NONE: {
      AP: ["RC-CLEAN-AP", "Clean AP document: standard process queue."],
      AR: ["RC-CLEAN-AR", "Clean AR document: standard open-item / cash-app path."],
    },
    DUPLICATE_INVOICE: [
      "RC-DUP-INV",
      "Possible duplicate invoice number in the same intake batch.",
    ],
    MISSING_PO: [
      "RC-PO-MISSING",
      "AP invoice exceeds the PO threshold and has no purchase order.",
    ],
    AMOUNT_VARIANCE: ["RC-AMT-VAR", "Remittance total and applied amount disagree."],
    UNKNOWN_COUNTERPARTY: [
      "RC-UNKNOWN-CPTY",
      "Counterparty is not on the synthetic vendor/customer master.",
    ],
    ENTITY_AMBIGUOUS: [
      "RC-ENTITY-AMBIG",
      "Could not resolve the document to a known legal entity.",
    ],
    UNALLOCATED_REMITTANCE: [
      "RC-REMIT-UNALLOC",
      "Cash received with an invoice reference that does not match an open item.",
    ],
    SHORT_PAY: ["RC-SHORT-PAY", "Customer remittance is short of the open invoice amount."],
    OVERPAYMENT: ["RC-OVERPAY", "Customer remittance exceeds the open invoice amount."],
    PAST_DUE: ["RC-PAST-DUE", "Document is past due as of the triage date."],
    MISSING_REMIT_ADVICE: [
      "RC-REMIT-NO-ADVICE",
      "Remittance arrived without invoice-level application detail.",
    ],
  };

  var PO_REQUIRED_CENTS = 50000;
  var CRITICAL_CENTS = 2500000;
  var HIGH_CENTS = 1000000;
  var HIGH_EXCEPTIONS = {
    SHORT_PAY: true,
    OVERPAYMENT: true,
    AMOUNT_VARIANCE: true,
    UNKNOWN_COUNTERPARTY: true,
    UNALLOCATED_REMITTANCE: true,
    MISSING_REMIT_ADVICE: true,
    ENTITY_AMBIGUOUS: true,
    DUPLICATE_INVOICE: true,
  };

  var JOURNAL_COLUMNS = ["GL Code", "Debit", "Credit", "Description"];
  var BILL_COLUMNS = [
    "Vendor",
    "Entity",
    "Occurrences",
    "Typical Amount",
    "Due Day Pattern",
    "Cadence",
    "Last Document",
    "Last Date",
  ];

  function scanText(text, source) {
    var lowered = String(text || "").toLowerCase();
    var hits = FORBIDDEN_TOKENS.filter(function (token) {
      return lowered.indexOf(token) !== -1;
    });
    if (hits.length) {
      throw new Error(
        source +
          " contains forbidden production tokens: " +
          hits.join(", ") +
          ". This demo is synthetic-only."
      );
    }
  }

  function cmp(left, right) {
    if (left < right) return -1;
    if (left > right) return 1;
    return 0;
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function parseDate(value) {
    var text = String(value || "").trim();
    if (!text) return null;
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (!match) {
      throw new Error("invalid date: " + text);
    }
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var utc = new Date(Date.UTC(year, month - 1, day));
    if (
      utc.getUTCFullYear() !== year ||
      utc.getUTCMonth() !== month - 1 ||
      utc.getUTCDate() !== day
    ) {
      throw new Error("invalid date: " + text);
    }
    return { y: year, m: month, d: day };
  }

  function isoDate(date) {
    return date.y + "-" + pad2(date.m) + "-" + pad2(date.d);
  }

  function shortDate(date) {
    return pad2(date.m) + "/" + pad2(date.d) + "/" + String(date.y).slice(-2).padStart(2, "0");
  }

  function daysBetween(later, earlier) {
    var a = Date.UTC(later.y, later.m - 1, later.d);
    var b = Date.UTC(earlier.y, earlier.m - 1, earlier.d);
    return Math.round((a - b) / 86400000);
  }

  function cmpDate(left, right) {
    return left.y - right.y || left.m - right.m || left.d - right.d;
  }

  function parseMoneyToCents(value) {
    if (value === null || typeof value === "undefined") {
      throw new Error("invalid amount: " + value);
    }
    var text = String(value).trim();
    if (!text) {
      throw new Error("invalid amount: " + value);
    }
    var negative = false;
    if (text[0] === "+" || text[0] === "-") {
      negative = text[0] === "-";
      text = text.slice(1);
    }
    if (!/^\d+(\.\d+)?$/.test(text)) {
      throw new Error("invalid amount: " + value);
    }
    var parts = text.split(".");
    var whole = parts[0];
    var frac = parts[1] || "";
    var pad = (frac + "000").slice(0, 3);
    var cents = BigInt(whole) * 100n + BigInt(pad.slice(0, 2));
    var roundDigit = Number(pad[2]);
    var restNonZero = frac.length > 3 && /[1-9]/.test(frac.slice(3));
    if (roundDigit > 5 || (roundDigit === 5 && restNonZero)) {
      cents += 1n;
    } else if (roundDigit === 5 && !restNonZero && cents % 2n === 1n) {
      cents += 1n;
    }
    if (negative) cents = -cents;
    if (cents > BigInt(Number.MAX_SAFE_INTEGER) || cents < -BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error("invalid amount: " + value);
    }
    return Number(cents);
  }

  function wholeDollarsFromCents(cents) {
    var sign = cents < 0 ? -1 : 1;
    var abs = Math.abs(cents);
    var dollars = Math.floor(abs / 100);
    var remainder = abs % 100;
    if (remainder >= 50) dollars += 1;
    return sign * dollars;
  }

  function formatMoney(cents) {
    var sign = cents < 0 ? "-" : "";
    var abs = Math.abs(cents);
    var dollars = String(Math.floor(abs / 100));
    var frac = pad2(abs % 100);
    var withCommas = dollars.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return "$" + sign + withCommas + "." + frac;
  }

  function normalizeName(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^\w\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function titleCase(value) {
    return String(value).replace(/[A-Za-z]+/g, function (word) {
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    });
  }

  function ordinalSuffix(day) {
    if (day >= 11 && day <= 13) return "th";
    return { 1: "st", 2: "nd", 3: "rd" }[day % 10] || "th";
  }

  function dueDayPattern(days, cadence) {
    var unique = [];
    days.forEach(function (day) {
      if (day && unique.indexOf(day) === -1) unique.push(day);
    });
    unique.sort(function (a, b) {
      return a - b;
    });
    if (!unique.length) return "Unknown";
    var label = String(cadence || "monthly").trim() || "monthly";
    if (unique.length === 1) {
      return titleCase(label) + " on the " + unique[0] + ordinalSuffix(unique[0]);
    }
    return "Mixed due days (" + unique.join(", ") + ")";
  }

  function medianWholeDollars(dollars) {
    var sorted = dollars.slice().sort(function (a, b) {
      return a - b;
    });
    var count = sorted.length;
    if (!count) return 0;
    if (count % 2 === 1) return sorted[(count - 1) / 2];
    var sum = sorted[count / 2 - 1] + sorted[count / 2];
    if (sum % 2 === 0) return sum / 2;
    return sum > 0 ? (sum + 1) / 2 : (sum - 1) / 2;
  }

  function parseCsv(text) {
    var rows = [];
    var row = [];
    var field = "";
    var inQuotes = false;
    var source = String(text || "").replace(/^\uFEFF/, "");
    for (var i = 0; i < source.length; i += 1) {
      var char = source[i];
      if (inQuotes) {
        if (char === '"') {
          if (source[i + 1] === '"') {
            field += '"';
            i += 1;
          } else {
            inQuotes = false;
          }
        } else {
          field += char;
        }
      } else if (char === '"') {
        inQuotes = true;
      } else if (char === ",") {
        row.push(field);
        field = "";
      } else if (char === "\n" || char === "\r") {
        if (char === "\r" && source[i + 1] === "\n") i += 1;
        row.push(field);
        field = "";
        if (row.some(function (cell) { return cell !== ""; })) rows.push(row);
        row = [];
      } else {
        field += char;
      }
    }
    if (field.length || row.length) {
      row.push(field);
      if (row.some(function (cell) { return cell !== ""; })) rows.push(row);
    }
    return rows;
  }

  function parseCsvRecords(text) {
    var rows = parseCsv(text);
    if (!rows.length) return [];
    var headers = rows[0];
    return rows.slice(1).map(function (cells) {
      var record = {};
      headers.forEach(function (header, index) {
        record[header] = cells[index] !== undefined ? cells[index] : "";
      });
      return record;
    });
  }

  function csvField(value) {
    var text = value === null || typeof value === "undefined" ? "" : String(value);
    if (/[",\r\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
    return text;
  }

  function toCsv(headers, records) {
    var lines = [headers.map(csvField).join(",")];
    records.forEach(function (record) {
      lines.push(headers.map(function (header) { return csvField(record[header]); }).join(","));
    });
    return lines.join("\r\n") + "\r\n";
  }

  function loadCatalog(text) {
    var raw = JSON.parse(text);
    var entities = (raw.entities || []).map(function (row) {
      return {
        id: row.id,
        legalName: row.legal_name,
        aliases: row.aliases || [],
        role: row.role || "operating",
      };
    });
    return {
      entities: entities,
      vendors: raw.vendors || [],
      customers: raw.customers || [],
    };
  }

  function resolveEntity(hint, catalog) {
    var needle = normalizeName(hint);
    if (!needle) return null;
    for (var i = 0; i < catalog.entities.length; i += 1) {
      var entity = catalog.entities[i];
      var candidates = [entity.legalName, entity.id].concat(entity.aliases);
      var exact = candidates.some(function (candidate) {
        return candidate && normalizeName(candidate) === needle;
      });
      if (exact) return entity;
      var partial = candidates.some(function (candidate) {
        return candidate && needle.length >= 4 && normalizeName(candidate).indexOf(needle) !== -1;
      });
      if (partial) return entity;
    }
    return null;
  }

  function knownCounterparty(name, catalog) {
    var needle = normalizeName(name);
    return catalog.vendors.concat(catalog.customers).some(function (item) {
      return normalizeName(item) === needle;
    });
  }

  function isCustomer(name, catalog) {
    var needle = normalizeName(name);
    return catalog.customers.some(function (item) {
      return normalizeName(item) === needle;
    });
  }

  function loadCoa(text) {
    var raw = JSON.parse(text);
    scanText(JSON.stringify(raw), "coa.json");
    var accounts = (raw.accounts || []).map(function (row) {
      return {
        code: String(row.code).trim(),
        name: String(row.name).trim(),
        type: String(row.type || "expense").trim(),
      };
    });
    if (!accounts.length) throw new Error("coa.json has no accounts");
    accounts.forEach(function (account) {
      if (account.code.indexOf("D-") !== 0) {
        throw new Error(
          "GL " + account.code + " is not dummy-prefixed (D-). This demo only ships fictional GLs."
        );
      }
    });
    var known = {};
    accounts.forEach(function (account) {
      known[account.code] = true;
    });
    var control = raw.control_accounts || {};
    var vendorGl = raw.vendor_gl || {};
    var customerGl = String(raw.customer_gl || "D-4000");
    var fallback = String(raw.fallback_expense_gl || "D-6600");
    Object.keys(control)
      .map(function (key) { return String(control[key]); })
      .concat(Object.keys(vendorGl).map(function (key) { return String(vendorGl[key]); }))
      .concat([customerGl, fallback])
      .forEach(function (code) {
        if (!known[code]) throw new Error("COA maps to unknown dummy GL " + code);
      });
    return {
      accounts: accounts,
      controlAccounts: { AP: String(control.AP), AR: String(control.AR) },
      vendorGl: vendorGl,
      customerGl: customerGl,
      fallback: fallback,
    };
  }

  function lookupVendorGl(counterparty, coa) {
    var needle = normalizeName(counterparty);
    var names = Object.keys(coa.vendorGl);
    for (var i = 0; i < names.length; i += 1) {
      if (normalizeName(names[i]) === needle) return String(coa.vendorGl[names[i]]);
    }
    return coa.fallback;
  }

  function loadInvoices(text) {
    return parseCsvRecords(text)
      .filter(function (row) {
        return String(row.doc_id || "").trim();
      })
      .map(function (row) {
        var kind = String(row.kind || "").trim();
        if (
          kind !== "vendor_invoice" &&
          kind !== "customer_invoice" &&
          kind !== "credit_memo"
        ) {
          throw new Error("invalid kind: " + kind);
        }
        return {
          docId: String(row.doc_id).trim(),
          kind: kind,
          entityHint: String(row.entity_hint || "").trim(),
          counterparty: String(row.counterparty || "").trim(),
          invoiceNumber: String(row.invoice_number || "").trim(),
          amountCents: parseMoneyToCents(row.amount || "0"),
          currency: String(row.currency || "USD").trim() || "USD",
          docDate: parseDate(row.doc_date || "") || { y: 1, m: 1, d: 1 },
          dueDate: parseDate(row.due_date || ""),
          poNumber: String(row.po_number || "").trim(),
          description: String(row.description || "").trim(),
          paymentRef: "",
          appliedInvoice: "",
          appliedAmountCents: null,
        };
      });
  }

  function loadRemittances(text) {
    var raw = JSON.parse(text);
    var rows = raw && !Array.isArray(raw) ? raw.remittances : raw;
    return (rows || []).map(function (row) {
      var applied = row.applied_amount;
      var invoiceRef = String(row.invoice_ref || "").trim();
      return {
        docId: String(row.doc_id).trim(),
        kind: "remittance",
        entityHint: String(row.entity_hint || "").trim(),
        counterparty: String(row.payer || "").trim(),
        invoiceNumber: invoiceRef,
        amountCents: parseMoneyToCents(row.amount === undefined ? "0" : row.amount),
        currency: String(row.currency || "USD").trim() || "USD",
        docDate: parseDate(String(row.payment_date || "")) || { y: 1, m: 1, d: 1 },
        dueDate: null,
        poNumber: "",
        description: String(row.description || "").trim(),
        paymentRef: String(row.payment_ref || row.invoice_ref || "").trim(),
        appliedInvoice: invoiceRef,
        appliedAmountCents:
          applied === null || typeof applied === "undefined" || applied === ""
            ? null
            : parseMoneyToCents(applied),
      };
    });
  }

  function sideFor(doc, catalog) {
    if (doc.kind === "remittance" || doc.kind === "customer_invoice") return "AR";
    if (doc.kind === "vendor_invoice") return "AP";
    if (knownCounterparty(doc.counterparty, catalog) && isCustomer(doc.counterparty, catalog)) {
      return "AR";
    }
    return "AP";
  }

  function daysPastDue(doc, asOf) {
    if (doc.kind === "remittance" || doc.kind === "credit_memo" || !doc.dueDate) return null;
    return daysBetween(asOf, doc.dueDate);
  }

  function duplicateNumbers(docs) {
    var counts = {};
    docs.forEach(function (doc) {
      if (doc.kind === "remittance" || !doc.invoiceNumber) return;
      counts[doc.invoiceNumber] = (counts[doc.invoiceNumber] || 0) + 1;
    });
    var duplicates = {};
    Object.keys(counts).forEach(function (number) {
      if (counts[number] > 1) duplicates[number] = true;
    });
    return duplicates;
  }

  function openInvoices(docs) {
    var mapping = {};
    docs.forEach(function (doc) {
      if (doc.kind === "remittance" || !doc.invoiceNumber) return;
      if (!mapping[doc.invoiceNumber]) mapping[doc.invoiceNumber] = doc;
    });
    return mapping;
  }

  function primaryException(flags) {
    var rank = {};
    EXCEPTION_PRIORITY.forEach(function (name, index) {
      rank[name] = index;
    });
    return flags.slice().sort(function (left, right) {
      return rank[left] - rank[right];
    })[0];
  }

  function urgencyFor(doc, exception, asOf) {
    var days = daysPastDue(doc, asOf);
    if (days !== null && days > 30) return "CRITICAL";
    if (exception === "DUPLICATE_INVOICE" && doc.amountCents >= HIGH_CENTS) return "CRITICAL";
    if (exception === "ENTITY_AMBIGUOUS" && doc.amountCents >= HIGH_CENTS) return "CRITICAL";
    if (doc.amountCents >= CRITICAL_CENTS && exception !== "NONE") return "CRITICAL";
    if (days !== null && days > 0) return "HIGH";
    if (days !== null && days >= -3 && exception !== "NONE") return "HIGH";
    if (HIGH_EXCEPTIONS[exception]) return "HIGH";
    if (exception === "MISSING_PO" && doc.amountCents >= HIGH_CENTS) return "HIGH";
    if (doc.kind === "credit_memo") return "LOW";
    if (days !== null && days < -45) return "LOW";
    return "NORMAL";
  }

  function collectFlags(doc, catalog, asOf, duplicates, invoices) {
    var flags = [];
    var notes = [];
    var entity = resolveEntity(doc.entityHint, catalog);
    var entityId = "";
    var entityName = doc.entityHint || "(blank)";
    if (!entity) {
      flags.push("ENTITY_AMBIGUOUS");
      notes.push("Entity hint did not resolve to a known legal entity; park for review.");
    } else {
      entityId = entity.id;
      entityName = entity.legalName;
    }
    if (!knownCounterparty(doc.counterparty, catalog)) {
      flags.push("UNKNOWN_COUNTERPARTY");
      notes.push("Counterparty " + JSON.stringify(doc.counterparty) + " is not on the vendor/customer master.");
    }
    if (doc.kind !== "remittance" && duplicates[doc.invoiceNumber]) {
      flags.push("DUPLICATE_INVOICE");
      notes.push("Invoice number " + doc.invoiceNumber + " appears more than once in the intake batch.");
    }
    if (doc.kind === "vendor_invoice" && doc.amountCents >= PO_REQUIRED_CENTS && !doc.poNumber) {
      flags.push("MISSING_PO");
      notes.push(
        "AP invoice " +
          (doc.amountCents / 100).toFixed(2) +
          " USD is above $500.00 and has no PO."
      );
    }
    if (doc.kind === "remittance") {
      var invoiceRef = doc.appliedInvoice || doc.invoiceNumber;
      if (!invoiceRef) {
        flags.push("MISSING_REMIT_ADVICE");
        notes.push("Remittance has no invoice reference to apply against.");
      } else {
        var matched = invoices[invoiceRef];
        if (!matched) {
          flags.push("UNALLOCATED_REMITTANCE");
          notes.push("No open invoice " + invoiceRef + " in this batch to apply cash against.");
        } else {
          var target = doc.appliedAmountCents === null ? doc.amountCents : doc.appliedAmountCents;
          if (doc.appliedAmountCents !== null && doc.appliedAmountCents !== doc.amountCents) {
            flags.push("AMOUNT_VARIANCE");
            notes.push(
              "Remittance total " +
                (doc.amountCents / 100).toFixed(2) +
                " does not equal applied amount " +
                (doc.appliedAmountCents / 100).toFixed(2) +
                "."
            );
          } else if (target < matched.amountCents) {
            flags.push("SHORT_PAY");
            notes.push(
              "Short pay: applied " +
                (target / 100).toFixed(2) +
                " against invoice " +
                (matched.amountCents / 100).toFixed(2) +
                "."
            );
          } else if (target > matched.amountCents) {
            flags.push("OVERPAYMENT");
            notes.push(
              "Overpay: applied " +
                (target / 100).toFixed(2) +
                " against invoice " +
                (matched.amountCents / 100).toFixed(2) +
                "."
            );
          } else {
            notes.push(
              "Cash matches open invoice " + invoiceRef + " at " + (matched.amountCents / 100).toFixed(2) + "."
            );
          }
        }
      }
    }
    var days = daysPastDue(doc, asOf);
    if (days !== null && days > 0) {
      flags.push("PAST_DUE");
      notes.push(
        "Due date " +
          isoDate(doc.dueDate) +
          " is " +
          days +
          " day(s) past as-of " +
          isoDate(asOf) +
          "."
      );
    }
    if (!flags.length) {
      flags.push("NONE");
      if (!notes.length) notes.push("No intake exceptions; ready for the standard queue.");
    }
    return { flags: flags, notes: notes, entityId: entityId, entityName: entityName };
  }

  function classifyDocuments(docs, catalog, asOf) {
    var duplicates = duplicateNumbers(docs);
    var invoices = openInvoices(docs);
    return docs.map(function (doc) {
      var collected = collectFlags(doc, catalog, asOf, duplicates, invoices);
      var exception = primaryException(collected.flags);
      return {
        document: doc,
        classification: {
          side: sideFor(doc, catalog),
          entityId: collected.entityId,
          entityName: collected.entityName,
          urgency: urgencyFor(doc, exception, asOf),
          exceptionType: exception,
          flags: collected.flags,
          notes: collected.notes,
        },
      };
    });
  }

  function reasonFor(classification) {
    var mapping = REASON_CODES[classification.exceptionType];
    if (mapping.AP) return mapping[classification.side];
    return mapping;
  }

  function queueFor(doc, classification) {
    if (classification.urgency === "CRITICAL") return "URGENT_ESCALATION";
    if (classification.exceptionType === "ENTITY_AMBIGUOUS") return "ENTITY_REVIEW";
    if (classification.side === "AP") {
      return classification.exceptionType === "NONE" ? "AP_PROCESS" : "AP_EXCEPTION";
    }
    if (doc.kind === "remittance") {
      return classification.exceptionType === "NONE" ? "AR_CASH_APPLICATION" : "AR_UNAPPLIED_CASH";
    }
    if (classification.exceptionType === "PAST_DUE") return "AR_COLLECTIONS";
    if (classification.exceptionType === "NONE") return "AR_OPEN_ITEMS";
    return "AR_COLLECTIONS";
  }

  function buildTriage(classified) {
    return classified.map(function (entry) {
      var queue = queueFor(entry.document, entry.classification);
      var reason = reasonFor(entry.classification);
      var code = reason[0];
      var rationale = reason[1];
      if (queue === "URGENT_ESCALATION" && entry.classification.exceptionType !== "NONE") {
        code = "RC-ESCALATE";
        rationale = "Critical urgency: " + rationale;
      }
      return {
        docId: entry.document.docId,
        kind: entry.document.kind,
        counterparty: entry.document.counterparty,
        amountCents: entry.document.amountCents,
        docDate: entry.document.docDate,
        dueDate: entry.document.dueDate,
        invoiceNumber: entry.document.invoiceNumber,
        side: entry.classification.side,
        entityId: entry.classification.entityId,
        entityName: entry.classification.entityName,
        urgency: entry.classification.urgency,
        exceptionType: entry.classification.exceptionType,
        flags: entry.classification.flags,
        notes: entry.classification.notes,
        queue: queue,
        reasonCode: code,
        rationale: rationale,
      };
    });
  }

  function compareQueueItem(left, right) {
    var leftCritical = left.urgency === "CRITICAL" ? 0 : 1;
    var rightCritical = right.urgency === "CRITICAL" ? 0 : 1;
    if (leftCritical !== rightCritical) return leftCritical - rightCritical;
    var leftHigh = left.urgency === "HIGH" ? 0 : 1;
    var rightHigh = right.urgency === "HIGH" ? 0 : 1;
    if (leftHigh !== rightHigh) return leftHigh - rightHigh;
    if (left.amountCents !== right.amountCents) return right.amountCents - left.amountCents;
    return cmp(left.docId, right.docId);
  }

  function journalableItems(items) {
    var seen = {};
    var selected = [];
    items.forEach(function (item) {
      if (item.kind === "remittance") return;
      if (item.exceptionType === "ENTITY_AMBIGUOUS") return;
      if (!item.entityId) return;
      if (item.invoiceNumber) {
        if (seen[item.invoiceNumber]) return;
        seen[item.invoiceNumber] = true;
      }
      selected.push(item);
    });
    return selected;
  }

  function signedDollars(item) {
    var amount = wholeDollarsFromCents(item.amountCents);
    if (item.kind === "credit_memo" || item.kind === "customer_invoice") return -amount;
    return amount;
  }

  function buildJournals(items, asOf, coa) {
    var groups = {};
    journalableItems(items).forEach(function (item) {
      var key = item.entityId + "\0" + item.entityName + "\0" + item.side;
      if (!groups[key]) {
        groups[key] = { entityId: item.entityId, entityName: item.entityName, side: item.side, items: [] };
      }
      groups[key].items.push(item);
    });
    return Object.keys(groups)
      .map(function (key) { return groups[key]; })
      .sort(function (left, right) {
        return cmp(left.entityId, right.entityId) || cmp(left.side, right.side);
      })
      .map(function (group) {
        var bucket = group.items.slice().sort(function (left, right) {
          return cmpDate(left.docDate, right.docDate) || cmp(left.docId, right.docId);
        });
        var lines = bucket.map(function (item) {
          var signed = signedDollars(item);
          var debit = signed >= 0 ? signed : 0;
          var credit = signed >= 0 ? 0 : -signed;
          var ref = item.invoiceNumber || item.docId;
          var gl = group.side === "AR" ? coa.customerGl : lookupVendorGl(item.counterparty, coa);
          var vendor = (item.counterparty || "Unknown").trim() || "Unknown";
          var documentRef = (ref || "NO-REF").trim() || "NO-REF";
          return {
            glCode: gl,
            debit: debit,
            credit: credit,
            description: shortDate(item.docDate) + " - " + vendor + "/" + documentRef,
          };
        });
        var net = lines.reduce(function (sum, line) {
          return sum + line.debit - line.credit;
        }, 0);
        if (net !== 0) {
          var control = group.side === "AP" ? coa.controlAccounts.AP : coa.controlAccounts.AR;
          var label = group.side === "AP" ? "Accounts Payable" : "Accounts Receivable";
          lines.push({
            glCode: control,
            debit: net < 0 ? -net : 0,
            credit: net > 0 ? net : 0,
            description: shortDate(asOf) + " - " + label,
          });
        }
        var debitTotal = lines.reduce(function (sum, line) { return sum + line.debit; }, 0);
        var creditTotal = lines.reduce(function (sum, line) { return sum + line.credit; }, 0);
        return {
          entityId: group.entityId,
          entityName: group.entityName,
          side: group.side,
          filename: group.entityId + "_" + group.side + ".csv",
          lines: lines,
          debitDollars: wholeDollarsFromCents(debitTotal * 100),
          creditDollars: wholeDollarsFromCents(creditTotal * 100),
        };
      });
  }

  function loadRecurring(text, catalog) {
    if (!String(text || "").trim()) return [];
    scanText(text, "recurring_bills.csv");
    var grouped = {};
    var order = [];
    parseCsvRecords(text).forEach(function (row) {
      var vendor = String(row.vendor || "").trim();
      if (!vendor) return;
      var hint = String(row.entity_hint || "").trim();
      var entity = resolveEntity(hint, catalog);
      var entityName = entity ? entity.legalName : hint || "(blank)";
      var key = vendor + "\0" + entityName;
      if (!grouped[key]) {
        grouped[key] = { vendor: vendor, entityName: entityName, rows: [] };
        order.push(key);
      }
      grouped[key].rows.push(row);
    });
    return order.map(function (key) {
      var group = grouped[key];
      var rows = group.rows.slice().sort(function (left, right) {
        return cmp(left.invoice_date || "", right.invoice_date || "");
      });
      var last = rows[rows.length - 1];
      var amounts = rows.map(function (row) {
        return wholeDollarsFromCents(parseMoneyToCents(row.amount || "0"));
      });
      var days = rows
        .map(function (row) { return String(row.due_day || ""); })
        .filter(function (day) { return /^\d+$/.test(day); })
        .map(function (day) { return Number(day); });
      var cadence = String(last.cadence || "monthly").trim() || "monthly";
      var lastDate = parseDate(last.invoice_date || "") || { y: 1, m: 1, d: 1 };
      return {
        vendor: group.vendor,
        entityName: group.entityName,
        occurrences: rows.length,
        typicalAmount: medianWholeDollars(amounts),
        dueDayPattern: dueDayPattern(days, cadence),
        cadence: cadence,
        lastDocument: String(last.document_ref || "").trim(),
        lastDate: lastDate,
      };
    });
  }

  function billControlFromIntake(items) {
    var grouped = {};
    var order = [];
    items.forEach(function (item) {
      if (item.kind !== "vendor_invoice" || item.side !== "AP" || !item.counterparty) return;
      var key = item.counterparty + "\0" + item.entityName;
      if (!grouped[key]) {
        grouped[key] = [];
        order.push(key);
      }
      grouped[key].push(item);
    });
    var rows = [];
    order.forEach(function (key) {
      var bucket = grouped[key];
      if (bucket.length < 2) return;
      bucket.sort(function (left, right) {
        return cmpDate(left.docDate, right.docDate) || cmp(left.docId, right.docId);
      });
      var last = bucket[bucket.length - 1];
      var amounts = bucket.map(function (item) { return wholeDollarsFromCents(item.amountCents); });
      var days = bucket.filter(function (item) { return item.dueDate; }).map(function (item) {
        return item.dueDate.d;
      });
      rows.push({
        vendor: bucket[0].counterparty,
        entityName: bucket[0].entityName,
        occurrences: bucket.length,
        typicalAmount: medianWholeDollars(amounts),
        dueDayPattern: dueDayPattern(days, "monthly"),
        cadence: "monthly",
        lastDocument: last.invoiceNumber || last.docId,
        lastDate: last.docDate,
      });
    });
    return rows;
  }

  function buildBillControl(items, catalog, recurringText) {
    var seen = {};
    var merged = [];
    loadRecurring(recurringText, catalog).concat(billControlFromIntake(items)).forEach(function (row) {
      var key = row.vendor + "\0" + row.entityName;
      if (seen[key]) return;
      seen[key] = true;
      merged.push(row);
    });
    merged.sort(function (left, right) {
      return cmp(left.vendor, right.vendor) || cmp(left.entityName, right.entityName);
    });
    return merged;
  }

  function buildView(items) {
    var byQueue = {};
    var byException = {};
    var byEntity = {};
    items.forEach(function (item) {
      if (!byQueue[item.queue]) byQueue[item.queue] = [];
      byQueue[item.queue].push(item);
      if (!byException[item.exceptionType]) byException[item.exceptionType] = [];
      byException[item.exceptionType].push(item);
      if (!byEntity[item.entityName]) byEntity[item.entityName] = [];
      byEntity[item.entityName].push(item);
    });
    var queues = QUEUE_ORDER.filter(function (queue) {
      return byQueue[queue] && byQueue[queue].length;
    }).map(function (queue) {
      var bucket = byQueue[queue].slice().sort(compareQueueItem);
      return {
        queue: queue,
        count: bucket.length,
        faceValueCents: bucket.reduce(function (sum, item) { return sum + item.amountCents; }, 0),
        hot: bucket.filter(function (item) {
          return item.urgency === "CRITICAL" || item.urgency === "HIGH";
        }).length,
        items: bucket,
      };
    });
    var exceptions = Object.keys(byException)
      .map(function (name) {
        var bucket = byException[name];
        return {
          name: name,
          count: bucket.length,
          faceValueCents: bucket.reduce(function (sum, item) { return sum + item.amountCents; }, 0),
        };
      })
      .sort(function (left, right) {
        return right.count - left.count || cmp(left.name, right.name);
      });
    var entities = Object.keys(byEntity)
      .map(function (name) {
        var bucket = byEntity[name];
        var ap = bucket.filter(function (item) { return item.side === "AP"; }).length;
        return {
          name: name,
          docs: bucket.length,
          ap: ap,
          ar: bucket.length - ap,
          exceptions: bucket.filter(function (item) { return item.exceptionType !== "NONE"; }).length,
        };
      })
      .sort(function (left, right) { return cmp(left.name, right.name); });
    return {
      queues: queues,
      exceptions: exceptions,
      entities: entities,
      documentCount: items.length,
      faceValueCents: items.reduce(function (sum, item) { return sum + item.amountCents; }, 0),
    };
  }

  function formatGenerated(generatedAt) {
    var date = generatedAt instanceof Date ? generatedAt : new Date(generatedAt || Date.now());
    if (Number.isNaN(date.getTime())) throw new Error("invalid generated time");
    return (
      date.getUTCFullYear() +
      "-" +
      pad2(date.getUTCMonth() + 1) +
      "-" +
      pad2(date.getUTCDate()) +
      " " +
      pad2(date.getUTCHours()) +
      ":" +
      pad2(date.getUTCMinutes()) +
      " UTC"
    );
  }

  function renderReport(model) {
    var lines = [
      "# AP/AR Intake Triage Report",
      "",
      "**Generated:** " + model.generatedLabel,
      "**As-of date:** " + model.asOfLabel,
      "**Source:** " + model.sourceLabel,
      "**Documents:** " +
        model.documentCount +
        " ingested · " +
        model.documentCount +
        " routed · " +
        formatMoney(model.faceValueCents) +
        " face value",
      "",
      "> Portfolio demo: fictional entities and amounts only. Not production software.",
      "",
      "## Queue summary",
      "",
      "| Queue | Count | Face value | Critical/High |",
      "| --- | ---: | ---: | ---: |",
    ];
    model.queues.forEach(function (bucket) {
      lines.push(
        "| `" +
          bucket.queue +
          "` | " +
          bucket.count +
          " | " +
          formatMoney(bucket.faceValueCents) +
          " | " +
          bucket.hot +
          " |"
      );
    });
    lines.push("", "## Exception mix", "", "| Exception | Count | Face value |", "| --- | ---: | ---: |");
    model.exceptions.forEach(function (row) {
      lines.push("| `" + row.name + "` | " + row.count + " | " + formatMoney(row.faceValueCents) + " |");
    });
    lines.push(
      "",
      "## By entity",
      "",
      "| Entity | Docs | AP | AR | Exceptions |",
      "| --- | ---: | ---: | ---: | ---: |"
    );
    model.entities.forEach(function (row) {
      lines.push(
        "| " + row.name + " | " + row.docs + " | " + row.ap + " | " + row.ar + " | " + row.exceptions + " |"
      );
    });
    if (model.journals.length) {
      lines.push(
        "",
        "## Journal pack",
        "",
        "Scrubbed dummy-GL journals (" +
          model.journals.length +
          ") written under `" +
          model.outputLabel +
          "`.",
        "Whole dollars only. Each file is one entity + AP or AR side, with a single payable/receivable balancing row.",
        "",
        "| Journal | Entity | Side | Lines | Debit | Credit | Balanced |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |"
      );
      model.journals.forEach(function (journal) {
        var balanced = journal.debitDollars === journal.creditDollars ? "yes" : "NO";
        lines.push(
          "| `" +
            journal.filename +
            "` | " +
            journal.entityName +
            " | " +
            journal.side +
            " | " +
            journal.lines.length +
            " | " +
            formatMoney(journal.debitDollars * 100) +
            " | " +
            formatMoney(journal.creditDollars * 100) +
            " | " +
            balanced +
            " |"
        );
      });
      if (model.billControl.length) {
        lines.push(
          "",
          "Bill control (recurring fictional vendors, including Acme Widgets and Stark Supplies) is in `bill_control.csv`."
        );
      }
    }
    lines.push("", "## Routed work", "");
    model.queues.forEach(function (bucket) {
      lines.push("### `" + bucket.queue + "`", "");
      lines.push(
        "| Doc | Side | Entity | Counterparty | Amount | Urgency | Exception | Reason | Why |"
      );
      lines.push("| --- | --- | --- | --- | ---: | --- | --- | --- | --- |");
      bucket.items.forEach(function (item) {
        var why = item.rationale.replace(/\|/g, "/");
        lines.push(
          "| `" +
            item.docId +
            "` | " +
            item.side +
            " | " +
            item.entityName +
            " | " +
            (item.counterparty || "-") +
            " | " +
            formatMoney(item.amountCents) +
            " | " +
            item.urgency +
            " | `" +
            item.exceptionType +
            "` | `" +
            item.reasonCode +
            "` | " +
            why +
            " |"
        );
      });
      lines.push("");
    });
    lines.push(
      "---",
      "",
      "Generated by `python3 -m apar_router`. Synthetic fixtures and dummy GLs only.",
      ""
    );
    return lines.join("\n");
  }

  function moneyCell(value) {
    return value === 0 ? "" : String(value);
  }

  function journalCsv(journal) {
    return toCsv(
      JOURNAL_COLUMNS,
      journal.lines.map(function (line) {
        return {
          "GL Code": line.glCode,
          Debit: moneyCell(line.debit),
          Credit: moneyCell(line.credit),
          Description: line.description,
        };
      })
    );
  }

  function billControlCsv(rows) {
    return toCsv(
      BILL_COLUMNS,
      rows.map(function (row) {
        return {
          Vendor: row.vendor,
          Entity: row.entityName,
          Occurrences: String(row.occurrences),
          "Typical Amount": String(row.typicalAmount),
          "Due Day Pattern": row.dueDayPattern,
          Cadence: row.cadence,
          "Last Document": row.lastDocument,
          "Last Date": row.lastDate && row.lastDate.y > 1 ? isoDate(row.lastDate) : "",
        };
      })
    );
  }

  function buildManifest(journalCount, billCount, paths) {
    var body = {
      synthetic: true,
      journals_balanced: true,
      journal_count: journalCount,
      bill_control_rows: billCount,
      files: paths,
    };
    return JSON.stringify(body, null, 2) + "\n";
  }

  function runPack(options) {
    var entitiesText = options.entitiesText;
    var invoicesText = options.invoicesText;
    var remittancesText = options.remittancesText;
    var coaText = options.coaText;
    var recurringText = options.recurringText || "";
    if (!entitiesText || !invoicesText || !remittancesText || !coaText) {
      throw new Error("The batch needs entities.json, invoices.csv, remittances.json, and coa.json.");
    }
    scanText(entitiesText, "entities.json");
    scanText(invoicesText, "invoices.csv");
    scanText(remittancesText, "remittances.json");
    scanText(coaText, "coa.json");
    if (recurringText) scanText(recurringText, "recurring_bills.csv");

    var asOf = parseDate(options.asOf);
    if (!asOf) throw new Error("Enter an as-of date like 2026-09-11.");
    var catalog = loadCatalog(entitiesText);
    var coa = loadCoa(coaText);
    var documents = loadInvoices(invoicesText).concat(loadRemittances(remittancesText));
    var items = buildTriage(classifyDocuments(documents, catalog, asOf));
    var journals = buildJournals(items, asOf, coa);
    journals.forEach(function (journal) {
      if (journal.debitDollars !== journal.creditDollars) {
        throw new Error(
          journal.filename +
            " is out of balance: debit " +
            journal.debitDollars +
            " != credit " +
            journal.creditDollars
        );
      }
    });
    var billControl = buildBillControl(items, catalog, recurringText);
    var view = buildView(items);
    var model = {
      generatedLabel: formatGenerated(options.generatedAt),
      asOfLabel: isoDate(asOf),
      sourceLabel: options.sourceLabel || "upload/ (synthetic)",
      outputLabel: options.outputLabel || "output/journals/",
      documentCount: view.documentCount,
      faceValueCents: view.faceValueCents,
      queues: view.queues,
      exceptions: view.exceptions,
      entities: view.entities,
      journals: journals,
      billControl: billControl,
    };
    var report = renderReport(model);
    scanText(report, "triage report");
    var files = [{ path: "triage_report.md", text: report }];
    journals.forEach(function (journal) {
      var csv = journalCsv(journal);
      scanText(csv, journal.filename);
      files.push({ path: "journals/" + journal.filename, text: csv });
    });
    var billCsv = billControlCsv(billControl);
    scanText(billCsv, "bill_control.csv");
    files.push({ path: "bill_control.csv", text: billCsv });
    var manifestPaths = files.map(function (file) { return file.path; }).concat(["manifest.json"]);
    var manifest = buildManifest(journals.length, billControl.length, manifestPaths);
    scanText(manifest, "manifest.json");
    files.push({ path: "manifest.json", text: manifest });
    return {
      report: report,
      files: files,
      asOf: model.asOfLabel,
      sourceLabel: model.sourceLabel,
      generatedLabel: model.generatedLabel,
      documentCount: model.documentCount,
      faceValueCents: model.faceValueCents,
      queues: model.queues,
      exceptions: model.exceptions,
      entities: model.entities,
      journals: journals,
      billControl: billControl,
    };
  }

  return { runPack: runPack, formatMoney: formatMoney };
});
