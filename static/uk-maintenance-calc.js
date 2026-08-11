/*
 * Rilono — UK Student visa maintenance-funds calculator (shared engine).
 *
 * ONE source of truth for the math, reused by:
 *   - the public tool page  (/tools/uk-maintenance-calculator)
 *   - the B2C student app    (Stage 4 "Finances & Healthcare" modal)
 *   - the Enterprise CRM      (consultant "Open calculator" on UK client pages)
 *
 * The FIGURES are NOT hardcoded here as the source of truth — they are fetched at load
 * from /api/tools/uk-maintenance-figures (server-side, env-overridable, with a best-effort
 * live GOV.UK check). The values below are only an instant fallback so the tool renders
 * immediately and still works if the API is unreachable; when the live figures arrive we
 * update every mounted calculator and any [data-ukm] prose in place. Always hedged with a
 * "confirm on GOV.UK" note in the UI.
 *
 * Exposes: window.RilonoUkMaintenanceCalc = { FIGURES, compute, dates, mount, openModal, loadFigures }
 */
(function () {
  "use strict";

  // Instant fallback only — the live values come from the server (see loadFigures()).
  // Confirmed against GOV.UK on 2026-08-07. The server re-reads the two monthly rates from
  // GOV.UK automatically; the accommodation-offset cap is NOT published on that page, so it
  // is a human-verified constant — £1,529 under Immigration Rules Appendix Student ST 12.4
  // (it offsets the funds required by ST 12.3), in force since 11 November 2025 via HC 1333.
  // `fieldSources` says which figures were live-verified.
  var FIGURES = {
    london: 1529,     // £/month living costs, studying in London
    outside: 1171,    // £/month living costs, outside London
    maxMonths: 9,     // maintenance is capped at 9 months of living costs
    accomCap: 1529,   // max accommodation prepayment (to the institution) you can offset
    asOf: "August 2026",
    source: "default",  // becomes "live" | "mixed" | "fallback" | "env" once fetched
    fieldSources: {},   // per-figure provenance, e.g. { london: "live", accomCap: "fallback" }
    sourceUrl: "https://www.gov.uk/student-visa/money",
    rulesUrl: "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-student",
    publicPath: "/tools/uk-maintenance-calculator",
  };

  var _subs = [];        // recompute/refresh callbacks for live-mounted calculators
  var _fetching = false;
  var _loaded = false;

  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }
  function gbp(n) { return "£" + Math.round(num(n)).toLocaleString("en-GB"); }
  function fmtDate(d) { return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  function compute(v) {
    v = v || {};
    var monthly = v.london ? FIGURES.london : FIGURES.outside;
    var months = Math.max(0, Math.min(FIGURES.maxMonths, num(v.months)));
    var living = monthly * months;
    var unpaidTuition = Math.max(0, num(v.tuition) - num(v.tuitionPaid));
    var accomOffset = Math.min(FIGURES.accomCap, Math.max(0, num(v.accomPaid)));
    var maintenance = Math.max(0, living - accomOffset);
    return {
      monthly: monthly, months: months, living: living,
      unpaidTuition: unpaidTuition, accomOffset: accomOffset,
      maintenance: maintenance, total: unpaidTuition + maintenance,
    };
  }

  function day(s) { if (!s) return null; var d = new Date(s + "T00:00:00"); return isNaN(d.getTime()) ? null : d; }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }

  // The 28-day window is anchored to the CLOSING DATE of the statement you submit, not to the
  // application date. GOV.UK (https://www.gov.uk/student-visa/money): "The end date of the
  // 28-day period must be within 31 days of the date you apply." So: hold from C−27 to C, and
  // C must be no earlier than (application date − 31). Anchoring the window to the application
  // date instead is over-strict — it can push a student to delay applying for no reason.
  // Both arguments are optional; pass either or both ("YYYY-MM-DD").
  function dates(appDateStr, closeDateStr) {
    var app = day(appDateStr), close = day(closeDateStr);
    if (!app && !close) return null;
    var anchor = close || app;                        // the 28-day period ends here
    return {
      app: app,
      close: close,
      anchor: anchor,
      holdStart: addDays(anchor, -27),                // 28 days inclusive of the end date
      earliestClose: app ? addDays(app, -31) : null,  // statement can't close before this
      latestApply: close ? addDays(close, 31) : null, // ...so this is your last day to apply
      closeTooEarly: !!(app && close && close < addDays(app, -31)),
      closeAfterApp: !!(app && close && close > app),
    };
  }

  // Fill any static prose marked up as <span data-ukm="london|outside|accomCap|maxMonths">
  // so the public page's explainer/FAQ text tracks the live figures too.
  function applyToProse(root) {
    var scope = root || document;
    if (!scope.querySelectorAll) return;
    scope.querySelectorAll("[data-ukm]").forEach(function (el) {
      var key = el.getAttribute("data-ukm");
      if (key === "maxMonths") el.textContent = String(FIGURES.maxMonths);
      else if (typeof FIGURES[key] === "number") el.textContent = gbp(FIGURES[key]);
      else if (typeof FIGURES[key] === "string") el.textContent = FIGURES[key];
    });
  }

  function _applyFigures(d) {
    if (!d || typeof d !== "object") return;
    ["london", "outside", "maxMonths", "accomCap", "asOf", "source", "fieldSources",
     "sourceUrl", "rulesUrl", "publicPath"].forEach(function (k) {
      if (d[k] != null) FIGURES[k] = d[k];
    });
    _loaded = true;
    // Refresh every live calculator instance, dropping any whose container has been removed.
    _subs = _subs.filter(function (s) {
      if (s.el && !document.body.contains(s.el)) return false;
      try { s.fn(); } catch (e) {}
      return true;
    });
    try { applyToProse(document); } catch (e) {}
  }

  // Pull the authoritative figures from the server (idempotent; safe to call repeatedly).
  function loadFigures() {
    if (_fetching || _loaded || typeof fetch !== "function") return;
    _fetching = true;
    fetch("/api/tools/uk-maintenance-figures", { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (d) { _fetching = false; _applyFigures(d); })
      .catch(function () { _fetching = false; });
  }

  var INP = "width:100%;box-sizing:border-box;background:#fff;border:1px solid #e2e8f0;border-radius:10px;color:#0f172a;font-size:14px;padding:10px 12px;font-family:inherit";
  function lbl(t) { return '<div style="font-size:12px;font-weight:700;color:#475569;margin:0 0 6px">' + t + "</div>"; }

  // The badge may only claim "live" for figures the server actually re-read from GOV.UK on
  // this check (FIGURES.fieldSources). The accommodation cap is not published on that page,
  // so it is named separately as our checked figure rather than riding along as live.
  function asOfHtml() {
    var fs = FIGURES.fieldSources || {};
    var govuk = 'confirm the current amounts on <a href="' + esc(FIGURES.sourceUrl) +
      '" target="_blank" rel="noopener" style="color:#6366f1;text-decoration:underline">GOV.UK</a>.';
    var ratesLive = (fs.london || FIGURES.source) === "live";
    var capLive = (fs.accomCap || FIGURES.source) === "live";
    if (ratesLive && capLive) {
      return '<span style="color:#16a34a;font-weight:700">✓ Live Home Office figures, verified from GOV.UK.</span> ' +
        'Amounts can change — always ' + govuk;
    }
    if (ratesLive) {
      return '<span style="color:#16a34a;font-weight:700">✓ Live monthly living-cost rates, verified from GOV.UK.</span> ' +
        "The " + gbp(FIGURES.accomCap) + " accommodation offset cap is our own checked figure (" +
        esc(FIGURES.asOf) + "), not a live reading — " + govuk;
    }
    return "Rates as of " + esc(FIGURES.asOf) + "; the Home Office updates these — always " + govuk;
  }

  // Render the interactive calculator (inputs + live result) INTO a container element.
  function mount(container) {
    if (!container) return;
    container.innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">' +
        '<div style="grid-column:1/-1">' + lbl("Where will you study?") +
          '<div class="ukm-loc" style="display:flex;gap:8px">' +
            '<button type="button" data-loc="outside" style="flex:1;padding:10px;border-radius:10px;border:1.5px solid #6366f1;background:#eef2ff;color:#4338ca;font-weight:700;cursor:pointer;font-family:inherit">Outside London</button>' +
            '<button type="button" data-loc="london" style="flex:1;padding:10px;border-radius:10px;border:1.5px solid #e2e8f0;background:#fff;color:#475569;font-weight:700;cursor:pointer;font-family:inherit">London</button>' +
          "</div></div>" +
        "<div>" + lbl("Course length (months)") + '<input class="ukm-months" type="number" min="1" max="12" value="9" style="' + INP + '"><div class="ukm-months-hint" style="font-size:11.5px;color:#94a3b8;margin-top:4px"></div></div>' +
        "<div>" + lbl("First-year tuition (£)") + '<input class="ukm-tuition" type="number" min="0" placeholder="e.g. 18000" style="' + INP + '"></div>' +
        "<div>" + lbl("Tuition already paid (£)") + '<input class="ukm-tuitionPaid" type="number" min="0" placeholder="e.g. 2000" style="' + INP + '"></div>' +
        "<div>" + lbl("Accommodation paid to your uni (£)") + '<input class="ukm-accom" type="number" min="0" placeholder="optional" style="' + INP + '"><div class="ukm-accom-hint" style="font-size:11.5px;color:#94a3b8;margin-top:4px"></div></div>' +
        "<div>" + lbl("Intended application date (optional)") + '<input class="ukm-appDate" type="date" style="' + INP + '"></div>' +
        "<div>" + lbl("Statement closing date (optional)") + '<input class="ukm-closeDate" type="date" style="' + INP + '"><div style="font-size:11.5px;color:#94a3b8;margin-top:4px">The last day covered by the statement you&#39;ll submit.</div></div>' +
      "</div>" +
      '<div class="ukm-result" style="margin-top:16px"></div>' +
      '<div class="ukm-asof" style="margin-top:12px;font-size:11.5px;color:#94a3b8"></div>';

    var state = { london: false };
    var q = function (sel) { return container.querySelector(sel); };
    var locBtns = container.querySelectorAll(".ukm-loc [data-loc]");

    locBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        state.london = b.getAttribute("data-loc") === "london";
        locBtns.forEach(function (x) {
          var on = x === b;
          x.style.borderColor = on ? "#6366f1" : "#e2e8f0";
          x.style.background = on ? "#eef2ff" : "#fff";
          x.style.color = on ? "#4338ca" : "#475569";
        });
        recompute();
      });
    });

    function row(a, b) {
      return '<div style="display:flex;justify-content:space-between;font-size:13px;color:#475569;padding:3px 0"><span>' + a + '</span><span style="font-weight:600;color:#0f172a">' + b + "</span></div>";
    }

    function recompute() {
      var r = compute({
        london: state.london,
        months: q(".ukm-months").value,
        tuition: q(".ukm-tuition").value,
        tuitionPaid: q(".ukm-tuitionPaid").value,
        accomPaid: q(".ukm-accom").value,
      });
      var d = dates(q(".ukm-appDate").value, q(".ukm-closeDate").value);
      var amt = gbp(r.total);
      // The 28 days end on the statement's closing date; the application date only sets how
      // late that closing date is allowed to be (within 31 days). Keep the copy and the dates
      // describing the same window — see dates() above.
      var hold = function (dd) {
        return "Hold at least <b>" + amt + "</b> in the account <b>every day</b> from <b>" +
          fmtDate(dd.holdStart) + "</b> to <b>" + fmtDate(dd.anchor) + "</b> (28 days), never dipping below it.";
      };
      var warn = function (t) { return '<span style="color:#b45309;font-weight:700">' + t + "</span>"; };
      var msg;
      if (d && d.close && d.app) {
        msg = "Your statement closes on <b>" + fmtDate(d.close) + "</b>, so that is the day your 28-day period ends. " + hold(d) + " " +
          (d.closeAfterApp
            ? warn("A statement can't close after the day you apply — use one closing on or before " + fmtDate(d.app) + ".")
            : d.closeTooEarly
              ? warn("That closing date is more than 31 days before " + fmtDate(d.app) + ".") +
                " Use a statement closing on or after <b>" + fmtDate(d.earliestClose) + "</b>, or apply by <b>" + fmtDate(d.latestApply) + "</b>."
              : "Applying on <b>" + fmtDate(d.app) + "</b> keeps that inside the 31-day limit.");
      } else if (d && d.close) {
        msg = "Your statement closes on <b>" + fmtDate(d.close) + "</b>. " + hold(d) +
          " Apply on or before <b>" + fmtDate(d.latestApply) + "</b> — the 28-day period has to end within 31 days of the day you apply.";
      } else if (d && d.app) {
        msg = "Applying on <b>" + fmtDate(d.app) + "</b>: the statement you submit must close between <b>" + fmtDate(d.earliestClose) +
          "</b> and <b>" + fmtDate(d.app) + "</b>, and you must hold at least <b>" + amt +
          "</b> every day for the 28 days ending on that closing date. Add the closing date for your exact window.";
      } else {
        msg = "Hold at least <b>" + amt + "</b> for <b>28 consecutive days</b> without dipping below it. The 28 days must end on your bank statement's closing date, and that date must be within <b>31 days</b> of the day you apply. Add your dates above for the exact window.";
      }
      var dateBox = '<div style="margin-top:8px;font-size:12.5px;color:#3730a3;line-height:1.6">' + msg + "</div>";
      q(".ukm-result").innerHTML =
        '<div style="background:linear-gradient(160deg,#f5f4ff,#eef2ff);border:1px solid rgba(99,102,241,.28);border-radius:14px;padding:16px 18px">' +
          '<div style="font-size:12px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:.05em">You must show</div>' +
          '<div style="font-size:32px;font-weight:850;letter-spacing:-.02em;margin:2px 0 10px">' + gbp(r.total) + "</div>" +
          row("Living costs (" + gbp(r.monthly) + " × " + r.months + " mo, " + (state.london ? "London" : "outside London") + ")", gbp(r.living)) +
          (r.accomOffset ? row("− Accommodation already paid", "−" + gbp(r.accomOffset)) : "") +
          row("Unpaid tuition (first year)", gbp(r.unpaidTuition)) +
          '<div style="border-top:1px dashed rgba(99,102,241,.3);margin:8px 0 6px"></div>' +
          row("<b>Total funds to show</b>", "<b>" + gbp(r.total) + "</b>") +
          '<div style="margin-top:10px;padding:10px 12px;background:#fff;border:1px solid rgba(99,102,241,.2);border-radius:10px">' +
            '<div style="font-size:12px;font-weight:700;color:#4338ca">📅 The 28-day rule</div>' + dateBox +
          "</div>" +
        "</div>";
    }

    // Refresh the figure-dependent static text, then recompute. Called on live-figure arrival.
    function refresh() {
      var mHint = q(".ukm-months-hint");
      if (mHint) mHint.textContent = "Living costs count for up to " + FIGURES.maxMonths + " months.";
      var aHint = q(".ukm-accom-hint");
      if (aHint) aHint.textContent = "Up to " + gbp(FIGURES.accomCap) + " can be offset.";
      var asof = q(".ukm-asof");
      if (asof) asof.innerHTML = asOfHtml();
      recompute();
    }

    ["ukm-months", "ukm-tuition", "ukm-tuitionPaid", "ukm-accom", "ukm-appDate", "ukm-closeDate"].forEach(function (cls) {
      var el = q("." + cls); if (el) el.addEventListener("input", recompute);
    });
    _subs.push({ el: container, fn: refresh });
    refresh();
    loadFigures();  // make sure the authoritative figures are (or get) loaded
  }

  // Open the calculator as a centered modal overlay (used by the B2C app + Enterprise CRM).
  function openModal(opts) {
    opts = opts || {};
    if (document.getElementById("ukmOverlay")) return;
    var overlay = document.createElement("div");
    overlay.id = "ukmOverlay";
    overlay.style.cssText = "position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(5,6,15,.55);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);overflow-y:auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Inter,sans-serif";
    overlay.innerHTML =
      '<div style="width:min(680px,100%);background:#fff;border:1px solid #e2e8f0;border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.35);overflow:hidden;color:#0f172a">' +
        '<div style="padding:22px 26px 8px;position:relative">' +
          '<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;font-weight:700">' + esc(opts.eyebrow || "UK Student visa · Maintenance funds") + "</div>" +
          '<h2 style="margin:8px 0 4px;font-size:22px;font-weight:800">💷 Maintenance funds calculator</h2>' +
          '<p style="margin:0;font-size:13.5px;color:#64748b">Work out the exact amount to show and the 28-day window your bank balance must cover.</p>' +
          '<button type="button" class="ukm-close" aria-label="Close" style="position:absolute;top:16px;right:18px;background:none;border:0;font-size:24px;line-height:1;color:#94a3b8;cursor:pointer">×</button>' +
        "</div>" +
        '<div style="padding:8px 26px 6px"><div class="ukm-body"></div></div>' +
        '<div style="padding:8px 26px 20px;display:flex;justify-content:flex-end">' +
          '<button type="button" class="ukm-done" style="border:none;border-radius:11px;padding:11px 22px;font-size:14px;font-weight:700;color:#fff;background:linear-gradient(135deg,#6366f1,#a855f7);cursor:pointer;font-family:inherit">Done</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(overlay);
    var prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function close() { overlay.remove(); document.body.style.overflow = prevOverflow; }
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    overlay.querySelector(".ukm-close").addEventListener("click", close);
    overlay.querySelector(".ukm-done").addEventListener("click", close);
    mount(overlay.querySelector(".ukm-body"));
  }

  window.RilonoUkMaintenanceCalc = {
    FIGURES: FIGURES, compute: compute, dates: dates,
    mount: mount, openModal: openModal, loadFigures: loadFigures,
  };

  // Kick off the authoritative-figure fetch as soon as the engine loads, and backfill any
  // [data-ukm] prose already on the page (e.g. the public tool page's explainer/FAQ).
  loadFigures();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { try { applyToProse(document); } catch (e) {} });
  } else {
    try { applyToProse(document); } catch (e) {}
  }
})();
