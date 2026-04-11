// jsvat.js stub — provided by anfepi_account_fix
// Minimal implementation of the jsvat VAT validation library.
// The partner_autocomplete module loads this file dynamically; this stub
// prevents the AssetsLoadingError when the original file is missing.
(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.jsvat = factory();
        root.checkVAT = root.jsvat.checkVAT;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function checkVAT(vat) {
        if (!vat) {
            return { value: '', isValid: false, isFormallyValid: false, country: undefined };
        }
        return { value: vat, isValid: false, isFormallyValid: false, country: undefined };
    }

    return { checkVAT: checkVAT };
}));
