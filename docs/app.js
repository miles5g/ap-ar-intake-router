(function () {
  "use strict";

  var REQUIRED = ["entities.json", "invoices.csv", "remittances.json", "coa.json"];
  var OPTIONAL = ["recurring_bills.csv"];
  var SLOTS = REQUIRED.concat(OPTIONAL);
  var uploads = {};
  var pack = null;
  var decisions = {};

  var QUEUE_PLAIN = {
    URGENT_ESCALATION: "Needs a person now.",
    ENTITY_REVIEW: "The company on the document is not identified.",
    AP_EXCEPTION: "Bills with a problem.",
    AP_PROCESS: "Bills ready to enter.",
    AR_UNAPPLIED_CASH: "Payments that do not match an open invoice.",
    AR_CASH_APPLICATION: "Payments ready to apply.",
    AR_COLLECTIONS: "Invoices to collect.",
    AR_OPEN_ITEMS: "Open invoices with nothing off.",
  };

  function $(id) {
    return document.getElementById(id);
  }

  function showError(message) {
    var node = $("error");
    if (!message) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = message;
  }

  function showScreen(name) {
    ["load", "run", "review"].forEach(function (step) {
      $("screen-" + step).hidden = step !== name;
    });
    showError("");
    window.scrollTo(0, 0);
  }

  function selectedSource() {
    var chosen = document.querySelector('input[name="source"]:checked');
    return chosen ? chosen.value : "sample";
  }

  function refreshLoadButton() {
    var upload = selectedSource() === "upload";
    $("upload-fields").hidden = !upload;
    var button = $("load-button");
    if (!upload) {
      button.textContent = "Load sample batch";
      button.disabled = false;
      return;
    }
    button.textContent = "Use these files";
    button.disabled = !REQUIRED.every(function (name) { return uploads[name]; });
  }

  function readFile(file) {
    return file.text();
  }

  async function loadSample() {
    var files = {};
    for (var i = 0; i < SLOTS.length; i += 1) {
      var name = SLOTS[i];
      var response = await fetch("sample/" + name);
      if (!response.ok) {
        throw new Error("The sample files could not be loaded. Open the hosted demo, or upload the files.");
      }
      files[name] = await response.text();
    }
    return files;
  }

  async function loadUploads() {
    var files = {};
    for (var i = 0; i < REQUIRED.length; i += 1) {
      var name = REQUIRED[i];
      if (!uploads[name]) throw new Error("Choose " + name + " before continuing.");
      files[name] = await readFile(uploads[name]);
    }
    if (uploads["recurring_bills.csv"]) {
      files["recurring_bills.csv"] = await readFile(uploads["recurring_bills.csv"]);
    } else {
      files["recurring_bills.csv"] = "";
    }
    return files;
  }

  function rememberBatch(files, sourceLabel) {
    window.__intakeBatch = { files: files, sourceLabel: sourceLabel };
    var list = $("loaded-files");
    list.replaceChildren();
    SLOTS.forEach(function (name) {
      if (name === "recurring_bills.csv" && !files[name]) return;
      var item = document.createElement("li");
      item.textContent = name;
      list.appendChild(item);
    });
    showScreen("run");
  }

  function cell(text, className) {
    var node = document.createElement("td");
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function headerRow(labels, numericFrom) {
    var row = document.createElement("tr");
    labels.forEach(function (label, index) {
      var node = document.createElement("th");
      node.scope = "col";
      node.textContent = label;
      if (index >= numericFrom) node.className = "num";
      row.appendChild(node);
    });
    return row;
  }

  function tableWrap(table) {
    var wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.appendChild(table);
    return wrap;
  }

  function makeTable(headers, numericFrom) {
    var table = document.createElement("table");
    var head = document.createElement("thead");
    head.appendChild(headerRow(headers, numericFrom));
    table.appendChild(head);
    var body = document.createElement("tbody");
    table.appendChild(body);
    return { table: table, body: body };
  }

  function section(title, note) {
    var block = document.createElement("section");
    block.className = "block";
    var heading = document.createElement("h2");
    heading.textContent = title;
    block.appendChild(heading);
    if (note) {
      var paragraph = document.createElement("p");
      paragraph.className = "note";
      paragraph.textContent = note;
      block.appendChild(paragraph);
    }
    return block;
  }

  function renderPack(result) {
    var root = $("results");
    root.replaceChildren();
    var meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent =
      result.documentCount +
      " documents. " +
      AparPipeline.formatMoney(result.faceValueCents) +
      " face value. As of " +
      result.asOf +
      ".";
    root.appendChild(meta);

    var flagged = flaggedItems(result);
    var review = section("Flagged items");
    var reviewStatus = document.createElement("p");
    reviewStatus.id = "review-status";
    reviewStatus.className = "note";
    review.appendChild(reviewStatus);
    if (!flagged.length) {
      var none = document.createElement("p");
      none.textContent = "Nothing is flagged.";
      review.appendChild(none);
    } else {
      var flagTable = makeTable(["Doc", "Exception", "Why", "Edit", "Decision"], 0);
      flagTable.table.className = "wide";
      flagged.forEach(function (item) {
        var row = document.createElement("tr");
        row.appendChild(cell(item.docId, "mono"));
        row.appendChild(cell(item.exceptionType, "mono"));
        row.appendChild(cell(item.rationale, "why"));
        var editCell = document.createElement("td");
        var input = document.createElement("input");
        input.type = "text";
        input.className = "note-input";
        input.setAttribute("aria-label", "Edit note for " + item.docId);
        input.placeholder = "Edit note";
        input.addEventListener("input", function () {
          if (input.value.trim()) decisions[item.docId] = "edited";
          else if (decisions[item.docId] === "edited") delete decisions[item.docId];
          refreshFinal();
        });
        editCell.appendChild(input);
        row.appendChild(editCell);
        var actionCell = document.createElement("td");
        var approve = document.createElement("button");
        approve.type = "button";
        approve.className = "row-action";
        approve.textContent = "Approve";
        approve.addEventListener("click", function () {
          decisions[item.docId] = "approved";
          approve.disabled = true;
          approve.textContent = "Approved";
          refreshFinal();
        });
        actionCell.appendChild(approve);
        row.appendChild(actionCell);
        flagTable.body.appendChild(row);
      });
      review.appendChild(tableWrap(flagTable.table));
    }
    root.appendChild(review);

    var queues = section("Queues");
    var queueTable = makeTable(["Queue", "What it is", "Count", "Face value", "Critical/High"], 2);
    result.queues.forEach(function (bucket) {
      var row = document.createElement("tr");
      var nameCell = document.createElement("td");
      var link = document.createElement("a");
      link.href = "#queue-" + bucket.queue;
      link.textContent = bucket.queue;
      link.className = "mono";
      nameCell.appendChild(link);
      row.appendChild(nameCell);
      row.appendChild(cell(QUEUE_PLAIN[bucket.queue] || ""));
      row.appendChild(cell(String(bucket.count), "num"));
      row.appendChild(cell(AparPipeline.formatMoney(bucket.faceValueCents), "num"));
      row.appendChild(cell(String(bucket.hot), "num"));
      queueTable.body.appendChild(row);
    });
    queues.appendChild(tableWrap(queueTable.table));
    root.appendChild(queues);

    var work = section("Documents");
    result.queues.forEach(function (bucket) {
      var block = document.createElement("div");
      block.className = "queue-block";
      block.id = "queue-" + bucket.queue;
      var heading = document.createElement("h3");
      var code = document.createElement("span");
      code.className = "mono";
      code.textContent = bucket.queue;
      heading.appendChild(code);
      block.appendChild(heading);
      var plain = document.createElement("p");
      plain.className = "note";
      plain.textContent = QUEUE_PLAIN[bucket.queue] || "";
      block.appendChild(plain);
      var docs = makeTable(
        ["Doc", "Side", "Entity", "Counterparty", "Amount", "Urgency", "Exception", "Reason", "Why"],
        4
      );
      docs.table.className = "wide";
      bucket.items.forEach(function (item) {
        var row = document.createElement("tr");
        row.appendChild(cell(item.docId, "mono"));
        row.appendChild(cell(item.side));
        row.appendChild(cell(item.entityName));
        row.appendChild(cell(item.counterparty || "-"));
        row.appendChild(cell(AparPipeline.formatMoney(item.amountCents), "num"));
        row.appendChild(cell(item.urgency));
        row.appendChild(cell(item.exceptionType, "mono"));
        row.appendChild(cell(item.reasonCode, "mono"));
        row.appendChild(cell(item.rationale, "why"));
        docs.body.appendChild(row);
      });
      block.appendChild(tableWrap(docs.table));
      work.appendChild(block);
    });
    root.appendChild(work);

    var journals = section("Journals");
    var journalNote = document.createElement("p");
    journalNote.id = "journal-note";
    journalNote.className = "note";
    journals.appendChild(journalNote);
    var journalTable = makeTable(["Journal", "Entity", "Side", "Lines", "Debit", "Credit", "Balanced"], 3);
    result.journals.forEach(function (journal) {
      var row = document.createElement("tr");
      var nameCell = document.createElement("td");
      var link = document.createElement("a");
      link.href = "#journal-" + journal.filename.replace(/\.csv$/, "");
      link.className = "mono";
      link.textContent = journal.filename;
      nameCell.appendChild(link);
      row.appendChild(nameCell);
      row.appendChild(cell(journal.entityName));
      row.appendChild(cell(journal.side));
      row.appendChild(cell(String(journal.lines.length), "num"));
      row.appendChild(cell(AparPipeline.formatMoney(journal.debitDollars * 100), "num"));
      row.appendChild(cell(AparPipeline.formatMoney(journal.creditDollars * 100), "num"));
      row.appendChild(cell("yes"));
      journalTable.body.appendChild(row);
    });
    journals.appendChild(tableWrap(journalTable.table));
    result.journals.forEach(function (journal) {
      var block = document.createElement("div");
      block.className = "queue-block";
      block.id = "journal-" + journal.filename.replace(/\.csv$/, "");
      var heading = document.createElement("h3");
      heading.className = "mono";
      heading.textContent = journal.filename;
      block.appendChild(heading);
      var lines = makeTable(["GL Code", "Debit", "Credit", "Description"], 1);
      journal.lines.forEach(function (line) {
        var row = document.createElement("tr");
        row.appendChild(cell(line.glCode, "mono"));
        row.appendChild(cell(line.debit ? String(line.debit) : "", "num"));
        row.appendChild(cell(line.credit ? String(line.credit) : "", "num"));
        row.appendChild(cell(line.description));
        lines.body.appendChild(row);
      });
      block.appendChild(tableWrap(lines.table));
      journals.appendChild(block);
    });
    root.appendChild(journals);

    var bills = section("Recurring bills");
    var billTable = makeTable(
      ["Vendor", "Entity", "Occurrences", "Typical amount", "Due day", "Last document", "Last date"],
      2
    );
    result.billControl.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(row.vendor));
      tr.appendChild(cell(row.entityName));
      tr.appendChild(cell(String(row.occurrences), "num"));
      tr.appendChild(cell(String(row.typicalAmount), "num"));
      tr.appendChild(cell(row.dueDayPattern));
      tr.appendChild(cell(row.lastDocument, "mono"));
      tr.appendChild(cell(row.lastDate && row.lastDate.y > 1 ? iso(row.lastDate) : ""));
      billTable.body.appendChild(tr);
    });
    bills.appendChild(tableWrap(billTable.table));
    root.appendChild(bills);

    var mix = section("Exception mix");
    var mixTable = makeTable(["Exception", "Count", "Face value"], 1);
    result.exceptions.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(row.name, "mono"));
      tr.appendChild(cell(String(row.count), "num"));
      tr.appendChild(cell(AparPipeline.formatMoney(row.faceValueCents), "num"));
      mixTable.body.appendChild(tr);
    });
    mix.appendChild(tableWrap(mixTable.table));
    root.appendChild(mix);

    var entities = section("By company");
    var entityTable = makeTable(["Entity", "Docs", "AP", "AR", "Exceptions"], 1);
    result.entities.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(row.name));
      tr.appendChild(cell(String(row.docs), "num"));
      tr.appendChild(cell(String(row.ap), "num"));
      tr.appendChild(cell(String(row.ar), "num"));
      tr.appendChild(cell(String(row.exceptions), "num"));
      entityTable.body.appendChild(tr);
    });
    entities.appendChild(tableWrap(entityTable.table));
    root.appendChild(entities);
    refreshFinal();
  }

  function flaggedItems(result) {
    var items = [];
    result.queues.forEach(function (bucket) {
      bucket.items.forEach(function (item) {
        if (item.exceptionType !== "NONE") items.push(item);
      });
    });
    return items;
  }

  function reviewComplete() {
    if (!pack) return false;
    return flaggedItems(pack).every(function (item) {
      return decisions[item.docId];
    });
  }

  function refreshFinal() {
    var ready = reviewComplete();
    var button = $("download-button");
    if (button) button.disabled = !ready;
    var status = $("review-status");
    if (status && pack) {
      var remaining = flaggedItems(pack).filter(function (item) {
        return !decisions[item.docId];
      }).length;
      status.textContent = ready
        ? "A person has approved or edited every flagged item."
        : remaining + " flagged items still need a person to approve or edit.";
    }
    var journalNote = $("journal-note");
    if (journalNote && pack) {
      journalNote.textContent = ready
        ? pack.journals.length + " journals, all balanced. A person reviewed the flags."
        : "Draft journals. A person approves or edits each flagged item before they are final.";
    }
  }

  function iso(date) {
    var month = String(date.m).padStart(2, "0");
    var day = String(date.d).padStart(2, "0");
    return date.y + "-" + month + "-" + day;
  }

  function runBatch() {
    var batch = window.__intakeBatch;
    var asOf = $("as-of").value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) {
      showError("Use a date like 2026-09-11.");
      return;
    }
    try {
      pack = AparPipeline.runPack({
        entitiesText: batch.files["entities.json"],
        invoicesText: batch.files["invoices.csv"],
        remittancesText: batch.files["remittances.json"],
        coaText: batch.files["coa.json"],
        recurringText: batch.files["recurring_bills.csv"] || "",
        asOf: asOf,
        sourceLabel: batch.sourceLabel,
        outputLabel: "output/journals/",
      });
    } catch (error) {
      showError(error && error.message ? error.message : "The batch could not be run.");
      return;
    }
    decisions = {};
    renderPack(pack);
    showScreen("review");
  }

  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n += 1) {
      var c = n;
      for (var k = 0; k < 8; k += 1) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    var c = 0xffffffff;
    for (var i = 0; i < bytes.length; i += 1) {
      c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    }
    return (c ^ 0xffffffff) >>> 0;
  }

  function buildZip(files) {
    var encoder = new TextEncoder();
    var now = new Date();
    var year = Math.max(now.getFullYear(), 1980);
    var dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
    var dosDate = ((year - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    var locals = [];
    var centrals = [];
    var offset = 0;
    files.forEach(function (file) {
      var name = encoder.encode(file.path);
      var data = encoder.encode(file.text);
      var crc = crc32(data);
      var local = new Uint8Array(30 + name.length + data.length);
      var view = new DataView(local.buffer);
      view.setUint32(0, 0x04034b50, true);
      view.setUint16(4, 20, true);
      view.setUint16(6, 0, true);
      view.setUint16(8, 0, true);
      view.setUint16(10, dosTime, true);
      view.setUint16(12, dosDate, true);
      view.setUint32(14, crc, true);
      view.setUint32(18, data.length, true);
      view.setUint32(22, data.length, true);
      view.setUint16(26, name.length, true);
      view.setUint16(28, 0, true);
      local.set(name, 30);
      local.set(data, 30 + name.length);
      locals.push(local);

      var central = new Uint8Array(46 + name.length);
      var centralView = new DataView(central.buffer);
      centralView.setUint32(0, 0x02014b50, true);
      centralView.setUint16(4, 20, true);
      centralView.setUint16(6, 20, true);
      centralView.setUint16(8, 0, true);
      centralView.setUint16(10, 0, true);
      centralView.setUint16(12, dosTime, true);
      centralView.setUint16(14, dosDate, true);
      centralView.setUint32(16, crc, true);
      centralView.setUint32(20, data.length, true);
      centralView.setUint32(24, data.length, true);
      centralView.setUint16(28, name.length, true);
      centralView.setUint16(30, 0, true);
      centralView.setUint16(32, 0, true);
      centralView.setUint16(34, 0, true);
      centralView.setUint16(36, 0, true);
      centralView.setUint32(38, 0, true);
      centralView.setUint32(42, offset, true);
      central.set(name, 46);
      centrals.push(central);
      offset += local.length;
    });
    var centralSize = centrals.reduce(function (sum, part) { return sum + part.length; }, 0);
    var end = new Uint8Array(22);
    var endView = new DataView(end.buffer);
    endView.setUint32(0, 0x06054b50, true);
    endView.setUint16(4, 0, true);
    endView.setUint16(6, 0, true);
    endView.setUint16(8, files.length, true);
    endView.setUint16(10, files.length, true);
    endView.setUint32(12, centralSize, true);
    endView.setUint32(16, offset, true);
    endView.setUint16(20, 0, true);
    var out = new Uint8Array(offset + centralSize + end.length);
    var cursor = 0;
    locals.concat(centrals, [end]).forEach(function (part) {
      out.set(part, cursor);
      cursor += part.length;
    });
    return out;
  }

  function downloadPack() {
    if (!pack || !reviewComplete()) return;
    var bytes = buildZip(pack.files);
    var blob = new Blob([bytes], { type: "application/zip" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "ap-ar-intake-pack.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function bind() {
    document.querySelectorAll('input[name="source"]').forEach(function (input) {
      input.addEventListener("change", refreshLoadButton);
    });
    document.querySelectorAll("input[type=file]").forEach(function (input) {
      input.addEventListener("change", function () {
        uploads[input.getAttribute("data-slot")] = input.files && input.files[0] ? input.files[0] : null;
        refreshLoadButton();
      });
    });
    $("load-button").addEventListener("click", async function () {
      var button = $("load-button");
      button.disabled = true;
      showError("");
      try {
        if (selectedSource() === "sample") {
          button.textContent = "Loading sample batch";
          rememberBatch(await loadSample(), "fixtures/ (synthetic)");
        } else {
          button.textContent = "Reading files";
          rememberBatch(await loadUploads(), "upload/ (synthetic)");
        }
      } catch (error) {
        showError(error && error.message ? error.message : "The files could not be loaded.");
      } finally {
        refreshLoadButton();
      }
    });
    $("run-button").addEventListener("click", runBatch);
    $("back-button").addEventListener("click", function () {
      showScreen("load");
    });
    $("download-button").addEventListener("click", downloadPack);
    $("restart-button").addEventListener("click", function () {
      pack = null;
      decisions = {};
      showScreen("load");
    });
    refreshLoadButton();
  }

  bind();
})();
