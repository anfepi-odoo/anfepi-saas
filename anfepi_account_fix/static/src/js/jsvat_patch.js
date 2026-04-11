/**
 * Patch: provide jsvat stub for partner_autocomplete in Odoo 18.
 *
 * In some Odoo 18 builds, /partner_autocomplete/static/lib/jsvat.js is
 * missing from the server. This causes partner_autocomplete's usePartnerAutocomplete
 * to throw AssetsLoadingError when opening forms with a partner field (e.g. invoices).
 *
 * This patch does two things:
 *  1. Defines window.jsvat and window.checkVAT so partner_autocomplete works.
 *  2. Pre-inserts a <script src="...jsvat.js"> tag into <head> so Odoo's
 *     loadJS() finds it already in the DOM and returns immediately without
 *     making an HTTP request that would fail with 404.
 */
(function () {
    "use strict";

    const JSVAT_URL = "/partner_autocomplete/static/lib/jsvat.js";

    // 1. Define global jsvat / checkVAT (what usePartnerAutocomplete uses)
    if (!window.jsvat) {
        window.jsvat = {
            checkVAT: function (vat) {
                return {
                    value: vat || "",
                    isValid: false,
                    isFormallyValid: false,
                    country: undefined,
                };
            },
        };
    }
    if (!window.checkVAT) {
        window.checkVAT = window.jsvat.checkVAT;
    }

    // 2. Pre-insert script tag so Odoo loadJS() sees it as already present
    //    and returns immediately without a network request.
    if (!document.head.querySelector('script[src="' + JSVAT_URL + '"]')) {
        var script = document.createElement("script");
        script.src = JSVAT_URL;
        // Silently absorb the potential 404 — it's expected here
        script.addEventListener("error", function (e) {
            e.stopImmediatePropagation();
        }, true);
        document.head.appendChild(script);
    }
})();
