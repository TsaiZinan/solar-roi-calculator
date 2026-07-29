// ==UserScript==
// @name         Codex Energy - Guangdong Spot Price Adapter
// @namespace    codex.energy
// @version      1.0.2
// @description  Extract public hourly real-time prices rendered by Guangdong Power Exchange.
// @match        https://pm.gd.csg.cn/portal/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function buildAdapter(globalScope) {
  "use strict";

  const SITE = "gd-csg-spot";
  const PRICE_KEYS = [
    "realtimeprice",
    "real_time_price",
    "realtimeclearingprice",
    "real_time_clearing_price",
    "rtprice",
  ];
  const TIME_KEYS = ["time", "datetime", "date_time", "period", "hour", "timestamp"];
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const capturedPayloads = [];

  function roundPrice(value) {
    return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  }

  function normalizeSeriesName(value) {
    return String(value == null ? "" : value).replace(/\s+/g, "");
  }

  function parseDate(value) {
    const text = String(value == null ? "" : value).trim();
    const match = text.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
    if (!match) return null;
    return `${match[1]}-${String(match[2]).padStart(2, "0")}-${String(match[3]).padStart(2, "0")}`;
  }

  function addDays(dateText, amount) {
    const [year, month, day] = dateText.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    date.setUTCDate(date.getUTCDate() + amount);
    return date.toISOString().slice(0, 10);
  }

  function dateRange(firstDate, lastDate) {
    const dates = [];
    for (let current = firstDate; current <= lastDate; current = addDays(current, 1)) {
      dates.push(current);
    }
    return dates;
  }

  function parsePointTime(label, index, total) {
    const text = String(label == null ? "" : label).trim();
    let match = text.match(/(?:^|[ T])(\d{1,2}):(\d{2})(?::\d{2})?(?:$|\s)/);
    if (!match) match = text.match(/^(\d{1,2}):(\d{2})$/);
    if (match) {
      const hour = Number(match[1]);
      const minute = Number(match[2]);
      if (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59) {
        return { hour, minute };
      }
    }

    match = text.match(/^(\d{1,2})(?:时|点)$/);
    if (match) {
      const hour = Number(match[1]);
      if (hour >= 0 && hour <= 23) return { hour, minute: 0 };
    }

    if (Number.isInteger(index) && Number.isInteger(total) && total >= 24 && 1440 % total === 0) {
      const minutes = index * (1440 / total);
      return { hour: Math.floor(minutes / 60), minute: minutes % 60 };
    }
    return null;
  }

  function aggregateHourly(points, targetDate) {
    const buckets = Array.from({ length: 24 }, () => []);
    const total = points.length;

    points.forEach((point, index) => {
      const label = point.label == null ? "" : String(point.label);
      const embeddedDate = parseDate(label);
      if (embeddedDate && embeddedDate !== targetDate) return;
      const parsedTime = parsePointTime(label, index, total);
      const price = Number(point.price);
      if (!parsedTime || !Number.isFinite(price)) return;
      buckets[parsedTime.hour].push(price);
    });

    if (buckets.some((bucket) => bucket.length === 0)) return null;
    return buckets.map((bucket, hour) => ({
      date: targetDate,
      hour: `${String(hour).padStart(2, "0")}:00`,
      realtime_price_yuan_per_MWh: roundPrice(
        bucket.reduce((sum, value) => sum + value, 0) / bucket.length
      ),
    }));
  }

  function valueFromSeriesItem(item) {
    if (typeof item === "number" || typeof item === "string") return Number(item);
    if (!item || typeof item !== "object") return NaN;
    const value = Object.prototype.hasOwnProperty.call(item, "value") ? item.value : item;
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) {
        const numeric = Number(value[index]);
        if (Number.isFinite(numeric)) return numeric;
      }
      return NaN;
    }
    return Number(value);
  }

  function labelFromSeriesItem(item, fallback) {
    if (item && typeof item === "object") {
      if (item.name != null) return item.name;
      if (Array.isArray(item.value) && item.value.length > 1) return item.value[0];
    }
    return fallback;
  }

  function extractFromEchartsOption(option, targetDate) {
    if (!option || typeof option !== "object") return null;
    const seriesList = Array.isArray(option.series) ? option.series : [];
    const realtimeSeries = seriesList.filter(
      (series) => normalizeSeriesName(series && series.name) === "实时价格"
    );
    if (realtimeSeries.length !== 1) return null;

    const series = realtimeSeries[0];
    const data = Array.isArray(series.data) ? series.data : [];
    if (data.length < 24) return null;
    const axes = Array.isArray(option.xAxis) ? option.xAxis : [option.xAxis];
    const axisIndex = Number.isInteger(series.xAxisIndex) ? series.xAxisIndex : 0;
    const axisData = Array.isArray(axes[axisIndex] && axes[axisIndex].data)
      ? axes[axisIndex].data
      : [];
    const points = data.map((item, index) => ({
      label: labelFromSeriesItem(item, axisData[index]),
      price: valueFromSeriesItem(item),
    }));
    return aggregateHourly(points, targetDate);
  }

  function objectValueByKeys(object, keys) {
    if (!object || typeof object !== "object") return undefined;
    const entries = Object.entries(object);
    for (const [key, value] of entries) {
      const normalized = key.replace(/[^a-z0-9_]/gi, "").toLowerCase();
      if (keys.includes(normalized)) return value;
    }
    return undefined;
  }

  function findResponseRows(node, targetDate, depth = 0) {
    if (depth > 7 || node == null) return null;
    if (Array.isArray(node)) {
      if (node.length >= 24 && node.every((item) => item && typeof item === "object")) {
        const points = node.map((item) => ({
          label: objectValueByKeys(item, TIME_KEYS),
          price: objectValueByKeys(item, PRICE_KEYS),
        }));
        const hourly = aggregateHourly(points, targetDate);
        if (hourly) return hourly;
      }
      for (const item of node.slice(0, 40)) {
        const result = findResponseRows(item, targetDate, depth + 1);
        if (result) return result;
      }
      return null;
    }
    if (typeof node === "object") {
      const optionRows = extractFromEchartsOption(node, targetDate);
      if (optionRows) return optionRows;

      const entries = Object.entries(node).slice(0, 60);
      for (const [key, value] of entries) {
        const normalizedKey = key.replace(/[^a-z0-9]/gi, "").toLowerCase();
        if (
          Array.isArray(value) &&
          value.length >= 24 &&
          value.every((item) => Number.isFinite(Number(item))) &&
          normalizedKey.includes("price") &&
          (normalizedKey.includes("real") || normalizedKey.startsWith("rt"))
        ) {
          const points = value.map((price, index) => ({ label: "", price }));
          const hourly = aggregateHourly(points, targetDate);
          if (hourly) return hourly;
        }
      }
      for (const value of entries.map((entry) => entry[1])) {
        const result = findResponseRows(value, targetDate, depth + 1);
        if (result) return result;
      }
    }
    return null;
  }

  function extractFromCapturedResponses(targetDate) {
    for (let index = capturedPayloads.length - 1; index >= 0; index -= 1) {
      const result = findResponseRows(capturedPayloads[index].payload, targetDate);
      if (result) return result;
    }
    return null;
  }

  function rememberPayload(payload, url) {
    if (!payload || typeof payload !== "object") return;
    capturedPayloads.push({ payload, url: String(url || "") });
    if (capturedPayloads.length > 20) capturedPayloads.shift();
  }

  function installPassiveCapture() {
    if (typeof globalScope.fetch === "function") {
      const originalFetch = globalScope.fetch;
      globalScope.fetch = function capturedFetch(...args) {
        return originalFetch.apply(this, args).then((response) => {
          try {
            const contentType = response.headers && response.headers.get("content-type");
            if (contentType && contentType.includes("json")) {
              response
                .clone()
                .json()
                .then((payload) => rememberPayload(payload, response.url))
                .catch(() => {});
            }
          } catch (_) {}
          return response;
        });
      };
    }

    if (typeof globalScope.XMLHttpRequest === "function") {
      const OriginalXHR = globalScope.XMLHttpRequest;
      const originalOpen = OriginalXHR.prototype.open;
      const originalSend = OriginalXHR.prototype.send;
      OriginalXHR.prototype.open = function capturedOpen(method, url, ...rest) {
        this.__codexSpotUrl = url;
        return originalOpen.call(this, method, url, ...rest);
      };
      OriginalXHR.prototype.send = function capturedSend(...args) {
        this.addEventListener(
          "load",
          () => {
            try {
              const contentType = this.getResponseHeader("content-type") || "";
              if (contentType.includes("json") && typeof this.responseText === "string") {
                rememberPayload(JSON.parse(this.responseText), this.__codexSpotUrl);
              }
            } catch (_) {}
          },
          { once: true }
        );
        return originalSend.apply(this, args);
      };
    }
  }

  function publish(fields) {
    if (typeof document === "undefined" || !document.documentElement) return;
    const dataset = document.documentElement.dataset;
    dataset.codexEnergySite = SITE;
    for (const [key, value] of Object.entries(fields)) {
      if (value == null) continue;
      dataset[key] = String(value);
    }
  }

  function updateStatusBadge(state, stage, errorCode) {
    if (!document.body) return;
    let badge = document.getElementById("codex-energy-price-status");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "codex-energy-price-status";
      Object.assign(badge.style, {
        position: "fixed",
        right: "24px",
        bottom: "76px",
        zIndex: "2147483647",
        maxWidth: "460px",
        padding: "8px 12px",
        border: "1px solid #90a4ae",
        borderRadius: "6px",
        background: "rgba(255,255,255,0.96)",
        color: "#263238",
        font: "12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif",
        boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
      });
      document.body.appendChild(badge);
    }
    badge.textContent = [SITE, state, stage, errorCode].filter(Boolean).join(" | ");
  }

  function setState(state, stage, errorCode = "") {
    publish({
      codexEnergyState: state,
      codexEnergyStage: stage,
      codexEnergyErrorCode: errorCode,
    });
    updateStatusBadge(state, stage, errorCode);
  }

  function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  async function waitUntil(check, timeoutMs, intervalMs = 500) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const result = check();
      if (result) return result;
      await sleep(intervalMs);
    }
    return null;
  }

  function elementText(element) {
    return String(element && element.textContent ? element.textContent : "")
      .replace(/\s+/g, "")
      .trim();
  }

  function findSpotSection() {
    const candidates = Array.from(
      document.querySelectorAll("div,section,article,h1,h2,h3,h4,h5,span")
    ).filter((element) => elementText(element) === "现货市场行情");

    for (const heading of candidates) {
      let ancestor = heading;
      for (let depth = 0; ancestor && depth < 10; depth += 1, ancestor = ancestor.parentElement) {
        const dateInputs = ancestor.querySelectorAll('input[placeholder*="日期"]');
        const hasChart = ancestor.querySelector("canvas,[_echarts_instance_]");
        if (dateInputs.length === 1 && hasChart) {
          return { section: ancestor, dateInput: dateInputs[0] };
        }
      }
    }
    return null;
  }

  function unitIsYuanPerMWh(section) {
    return /元\s*\/\s*MWh/i.test(String(section.textContent || ""));
  }

  function inputDate(input) {
    return parseDate(input && input.value);
  }

  function nativeSetInputValue(input, value) {
    const descriptor = Object.getOwnPropertyDescriptor(
      globalScope.HTMLInputElement.prototype,
      "value"
    );
    if (descriptor && descriptor.set) descriptor.set.call(input, value);
    else input.value = value;
    for (const type of ["input", "change"]) {
      input.dispatchEvent(new Event(type, { bubbles: true }));
    }
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true })
    );
    input.dispatchEvent(
      new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true })
    );
    input.blur();
  }

  function visibleElement(element) {
    if (!element) return false;
    const style = globalScope.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 &&
      rect.width > 0 &&
      rect.height > 0
    );
  }

  async function chooseExactDateCell(input, targetDate) {
    input.click();
    await sleep(300);
    const selectors = [
      `td[title="${targetDate}"]`,
      `[role="gridcell"][title="${targetDate}"]`,
      `td[aria-label="${targetDate}"]`,
      `[role="gridcell"][aria-label="${targetDate}"]`,
      `[title="${targetDate}"]`,
      `[aria-label="${targetDate}"]`,
      `[data-date="${targetDate}"]`,
      `[data-value="${targetDate}"]`,
    ];
    for (const selector of selectors) {
      const matches = Array.from(document.querySelectorAll(selector)).filter(visibleElement);
      if (matches.length === 1) {
        matches[0].click();
        return true;
      }
    }

    const [targetYear, targetMonth, targetDay] = targetDate.split("-").map(Number);
    const visibleCells = Array.from(
      document.querySelectorAll('td,[role="gridcell"]')
    ).filter(visibleElement);
    const dayMatches = visibleCells.filter((cell) => {
      const label = [
        cell.getAttribute("title"),
        cell.getAttribute("aria-label"),
        cell.getAttribute("data-date"),
        cell.getAttribute("data-value"),
      ]
        .filter(Boolean)
        .join(" ");
      if (parseDate(label) === targetDate) return true;
      const classes = String(cell.className || "").toLowerCase();
      if (/prev|next|disabled|other/.test(classes)) return false;
      return elementText(cell) === String(targetDay);
    });
    if (dayMatches.length !== 1) return false;

    const pickerText = elementText(
      dayMatches[0].closest(
        '.ant-picker-dropdown,.ant-calendar-picker-container,.el-picker-panel,[role="dialog"]'
      ) || dayMatches[0].parentElement
    );
    const yearMatches = pickerText.includes(`${targetYear}年`) || pickerText.includes(String(targetYear));
    const monthMatches =
      pickerText.includes(`${targetMonth}月`) ||
      pickerText.includes(`${String(targetMonth).padStart(2, "0")}月`);
    if (!yearMatches || !monthMatches) return false;
    dayMatches[0].click();
    return true;
  }

  async function setPageDate(input, targetDate) {
    if (inputDate(input) === targetDate) return true;
    input.focus();
    nativeSetInputValue(input, targetDate);
    let confirmed = await waitUntil(() => inputDate(input) === targetDate, 3000, 200);
    if (confirmed) return true;
    await chooseExactDateCell(input, targetDate);
    confirmed = await waitUntil(() => inputDate(input) === targetDate, 5000, 250);
    return Boolean(confirmed);
  }

  function getEchartsOptions(section) {
    if (!globalScope.echarts || typeof globalScope.echarts.getInstanceByDom !== "function") {
      return [];
    }
    const roots = Array.from(section.querySelectorAll("[_echarts_instance_]"));
    return roots
      .map((root) => {
        try {
          const instance = globalScope.echarts.getInstanceByDom(root);
          return instance && typeof instance.getOption === "function" ? instance.getOption() : null;
        } catch (_) {
          return null;
        }
      })
      .filter(Boolean);
  }

  function extractRenderedPrices(section, targetDate) {
    const captured = extractFromCapturedResponses(targetDate);
    if (captured) return { rows: captured, source: "page_response" };

    const options = getEchartsOptions(section);
    const matches = options
      .map((option) => extractFromEchartsOption(option, targetDate))
      .filter(Boolean);
    if (matches.length !== 1) return null;
    return { rows: matches[0], source: "echarts" };
  }

  async function waitForPrices(section, dateInput, targetDate) {
    return waitUntil(() => {
      if (inputDate(dateInput) !== targetDate) return null;
      return extractRenderedPrices(section, targetDate);
    }, 60000, 750);
  }

  function rowsToCsv(rows) {
    const lines = ["date,hour,realtime_price_yuan_per_MWh"];
    rows.forEach((row) => {
      lines.push(
        `${row.date},${row.hour},${Number(row.realtime_price_yuan_per_MWh).toFixed(2)}`
      );
    });
    return `${lines.join("\n")}\n`;
  }

  function safeRunId(runId) {
    return String(runId || "manual").replace(/[^a-zA-Z0-9._-]/g, "_");
  }

  function installDownloadButton(csvText, filename) {
    const existing = document.getElementById("codex-energy-price-download");
    if (existing) existing.remove();
    const button = document.createElement("button");
    button.id = "codex-energy-price-download";
    button.type = "button";
    button.textContent = "下载实时电价 CSV";
    Object.assign(button.style, {
      position: "fixed",
      right: "24px",
      bottom: "24px",
      zIndex: "2147483647",
      padding: "10px 16px",
      border: "1px solid #1769aa",
      borderRadius: "6px",
      background: "#1976d2",
      color: "#fff",
      fontSize: "14px",
      cursor: "pointer",
    });
    button.addEventListener("click", () => {
      const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setState("download_started", "candidate_csv_download_triggered");
    });
    document.body.appendChild(button);
    return button;
  }

  function buildCandidate(collected, runId) {
    if (!Array.isArray(collected) || collected.length === 0) return null;
    const firstDate = collected[0].date;
    const lastDate = collected.at(-1).date;
    return {
      csvText: rowsToCsv(collected),
      filename:
        `spot_realtime_prices_web_${firstDate}_to_${lastDate}` +
        `_${safeRunId(runId)}.csv`,
      firstDate,
      lastDate,
    };
  }

  async function publishCandidate(collected, runId, source, stage, errorCode = "") {
    const candidate = buildCandidate(collected, runId);
    if (!candidate) return false;
    const button = installDownloadButton(candidate.csvText, candidate.filename);
    publish({
      codexEnergyExtractedFrom: candidate.firstDate,
      codexEnergyExtractedTo: candidate.lastDate,
      codexEnergyRecordCount: collected.length,
      codexEnergySource: source,
    });
    setState("ready_download", stage, errorCode);
    await sleep(100);
    button.click();
    return true;
  }

  async function run() {
    const parameters = new URLSearchParams(globalScope.location.search);
    if (parameters.get("codex-energy-mode") !== "spot-price") return;

    const runId = parameters.get("codex-energy-run") || "";
    const afterDate = parameters.get("codex-energy-after") || "";
    publish({ codexEnergyRunId: runId, codexEnergyTargetDate: afterDate });
    if (!DATE_PATTERN.test(afterDate)) {
      setState("failed", "validating_parameters", "INVALID_AFTER_DATE");
      return;
    }

    setState("loading", "waiting_for_spot_market_section");
    const context = await waitUntil(findSpotSection, 180000, 1000);
    if (!context) {
      setState("unavailable", "waiting_for_spot_market_section", "PAGE_TIMEOUT");
      return;
    }
    if (!unitIsYuanPerMWh(context.section)) {
      setState("failed", "validating_chart_unit", "UNIT_MISMATCH");
      return;
    }

    const latestDate = inputDate(context.dateInput);
    if (!latestDate) {
      setState("failed", "reading_latest_date", "DATE_CONTROL_UNSUPPORTED");
      return;
    }
    publish({ codexEnergyLatestDate: latestDate });
    if (latestDate <= afterDate) {
      setState("no_new_data", "comparing_latest_date");
      return;
    }

    const requestedDates = dateRange(addDays(afterDate, 1), latestDate);
    const collected = [];
    let source = "";
    setState("extracting", "collecting_hourly_prices");

    for (const targetDate of requestedDates) {
      capturedPayloads.length = 0;
      const dateSet = await setPageDate(context.dateInput, targetDate);
      if (!dateSet) {
        setState("failed", "setting_chart_date", "DATE_MISMATCH");
        return;
      }
      const extracted = await waitForPrices(context.section, context.dateInput, targetDate);
      if (!extracted) {
        if (collected.length > 0) {
          await publishCandidate(
            collected,
            runId,
            source,
            "candidate_csv_ready_before_gap",
            "DATE_DATA_UNAVAILABLE"
          );
          return;
        }
        setState("unavailable", "waiting_for_date_data", "DATE_DATA_UNAVAILABLE");
        return;
      }
      if (extracted.rows.length !== 24) {
        setState("failed", "validating_hourly_prices", "DATA_INCOMPLETE");
        return;
      }
      collected.push(...extracted.rows);
      source = source ? `${source}+${extracted.source}` : extracted.source;
      publish({
        codexEnergyExtractedFrom: requestedDates[0],
        codexEnergyExtractedTo: targetDate,
        codexEnergyRecordCount: collected.length,
        codexEnergySource: source,
      });
    }

    await publishCandidate(
      collected,
      runId,
      source,
      "candidate_csv_ready"
    );
  }

  const testApi = {
    addDays,
    aggregateHourly,
    buildCandidate,
    dateRange,
    extractFromEchartsOption,
    parseDate,
    parsePointTime,
    rowsToCsv,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = testApi;
  }
  if (typeof document !== "undefined" && globalScope.location) {
    installPassiveCapture();
    run().catch(() => {
      setState("failed", "unexpected_adapter_error", "ADAPTER_EXCEPTION");
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
