import { createRequire } from "node:module";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const { runPack } = require("../docs/pipeline.js");

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index === -1 || !process.argv[index + 1]) {
    throw new Error("missing " + name);
  }
  return process.argv[index + 1];
}

const fixtures = arg("--fixtures");
const out = arg("--out");
const read = (name) => readFileSync(join(fixtures, name), "utf8");
const pack = runPack({
  entitiesText: read("entities.json"),
  invoicesText: read("invoices.csv"),
  remittancesText: read("remittances.json"),
  coaText: read("coa.json"),
  recurringText: read("recurring_bills.csv"),
  asOf: arg("--as-of"),
  sourceLabel: "fixtures/ (synthetic)",
  outputLabel: "output/journals/",
  generatedAt: arg("--generated-at"),
});

for (const file of pack.files) {
  const path = join(out, file.path);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, file.text);
}
