/*
 * First-touch acquisition capture.
 *
 * Records where a visitor originally came from (UTM tags + document.referrer) on their
 * FIRST landing, and keeps it in localStorage until they sign up. app.js reads it and
 * sends it to /api/auth/register, where the backend normalizes it into a channel for the
 * admin traffic-source breakdown.
 *
 * First-touch is preserved once a *meaningful* source is known — but a source-less
 * "direct" first visit is upgraded if the visitor later arrives via a real source.
 */
(function () {
    var KEY = "rilono_attribution";
    try {
        var params = new URLSearchParams(window.location.search);
        var utmSource = (params.get("utm_source") || "").slice(0, 200);
        var utmMedium = (params.get("utm_medium") || "").slice(0, 100);
        var utmCampaign = (params.get("utm_campaign") || "").slice(0, 200);
        var referrer = document.referrer || "";

        // Is this visit external (a real off-site source), not internal navigation?
        var externalRef = false;
        if (referrer) {
            try { externalRef = new URL(referrer).host.indexOf(window.location.host) === -1; }
            catch (e) { externalRef = referrer.indexOf(window.location.host) === -1; }
        }
        var hasSourceNow = !!(utmSource || externalRef);

        var existing = null;
        try { existing = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { existing = null; }

        // Keep the existing record if it already captured a meaningful source (true first-touch).
        if (existing && existing._src) return;
        // Nothing new to add and nothing stored worth keeping → wait for a better visit.
        if (!hasSourceNow && existing) return;

        localStorage.setItem(KEY, JSON.stringify({
            utm_source: utmSource,
            utm_medium: utmMedium,
            utm_campaign: utmCampaign,
            referrer: referrer.slice(0, 500),
            landing: (window.location.pathname + window.location.search).slice(0, 500),
            _src: hasSourceNow,
            ts: Date.now()
        }));
    } catch (e) { /* storage blocked (private mode) — attribution simply won't be captured */ }
})();

/* Reader used by the signup flow. Returns the register payload keys, or {}. */
window.getRilonoAttribution = function () {
    try {
        var a = JSON.parse(localStorage.getItem("rilono_attribution") || "null");
        if (!a) return {};
        return {
            acq_source: a.utm_source || "",
            acq_medium: a.utm_medium || "",
            acq_campaign: a.utm_campaign || "",
            acq_referrer: a.referrer || "",
            acq_landing: a.landing || ""
        };
    } catch (e) { return {}; }
};
