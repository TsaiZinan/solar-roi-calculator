"use strict";

const assert = require("assert");
const adapter = require("../tampermonkey/gd_spot_prices.user.js");

function hourlyOption(values, labels) {
  return {
    xAxis: [{ data: labels }],
    series: [
      { name: "日前价格", data: values.map((value) => value + 10) },
      { name: "实时价格", data: values },
    ],
  };
}

const hourlyValues = Array.from({ length: 24 }, (_, hour) => hour - 5);
const hourlyLabels = Array.from(
  { length: 24 },
  (_, hour) => `${String(hour).padStart(2, "0")}:00`
);
const hourly = adapter.extractFromEchartsOption(
  hourlyOption(hourlyValues, hourlyLabels),
  "2026-07-15"
);
assert.strictEqual(hourly.length, 24);
assert.strictEqual(hourly[0].realtime_price_yuan_per_MWh, -5);
assert.strictEqual(hourly[23].hour, "23:00");

const quarterHourValues = Array.from({ length: 96 }, (_, index) => index);
const quarterHourLabels = Array.from({ length: 96 }, (_, index) => {
  const hour = Math.floor(index / 4);
  const minute = (index % 4) * 15;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
});
const quarterHourly = adapter.extractFromEchartsOption(
  hourlyOption(quarterHourValues, quarterHourLabels),
  "2026-07-15"
);
assert.strictEqual(quarterHourly.length, 24);
assert.strictEqual(quarterHourly[0].realtime_price_yuan_per_MWh, 1.5);
assert.strictEqual(quarterHourly[23].realtime_price_yuan_per_MWh, 93.5);

const missingHour = quarterHourLabels.filter((label) => !label.startsWith("07:"));
const missingValues = quarterHourValues.slice(0, missingHour.length);
assert.strictEqual(
  adapter.aggregateHourly(
    missingHour.map((label, index) => ({ label, price: missingValues[index] })),
    "2026-07-15"
  ),
  null
);

assert.deepStrictEqual(adapter.dateRange("2026-07-30", "2026-08-02"), [
  "2026-07-30",
  "2026-07-31",
  "2026-08-01",
  "2026-08-02",
]);
assert.strictEqual(adapter.parseDate("2026/7/5"), "2026-07-05");
assert.strictEqual(adapter.parsePointTime("2026-07-15 08:30", 0, 96).hour, 8);

const csv = adapter.rowsToCsv(hourly);
assert.ok(csv.startsWith("date,hour,realtime_price_yuan_per_MWh\n"));
assert.ok(csv.includes("2026-07-15,00:00,-5.00"));

const partialCandidate = adapter.buildCandidate(
  [
    ...hourly,
    ...hourly.map((row) => ({ ...row, date: "2026-07-16" })),
  ],
  "spot-2026-07-30-3"
);
assert.strictEqual(partialCandidate.firstDate, "2026-07-15");
assert.strictEqual(partialCandidate.lastDate, "2026-07-16");
assert.strictEqual(
  partialCandidate.filename,
  "spot_realtime_prices_web_2026-07-15_to_2026-07-16_spot-2026-07-30-3.csv"
);
assert.strictEqual(adapter.buildCandidate([], "empty"), null);

console.log("gd_spot_prices tests passed");
