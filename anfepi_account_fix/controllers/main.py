# -*- coding: utf-8 -*-
import os
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

_JSVAT_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'static', 'lib', 'jsvat.js'
)


class JsvatFallback(http.Controller):
    """
    Sirve jsvat.js en la ruta que partner_autocomplete carga dinámicamente
    cuando el archivo original no existe en el servidor.
    """

    @http.route(
        '/partner_autocomplete/static/lib/jsvat.js',
        type='http',
        auth='public',
        csrf=False,
        methods=['GET'],
    )
    def jsvat_fallback(self, **kwargs):
        # Si el archivo original existe en partner_autocomplete, no intervenimos.
        try:
            from odoo.modules import get_module_path
            original = os.path.join(
                get_module_path('partner_autocomplete') or '',
                'static', 'lib', 'jsvat.js',
            )
            if os.path.isfile(original):
                with open(original, 'rb') as f:
                    content = f.read()
                return Response(
                    content,
                    content_type='application/javascript; charset=utf-8',
                    headers=[('Cache-Control', 'public, max-age=604800')],
                )
        except Exception:
            pass

        # Fallback: servir nuestro stub
        with open(_JSVAT_PATH, 'rb') as f:
            content = f.read()
        _logger.debug('anfepi_account_fix: sirviendo jsvat.js stub (archivo original no encontrado)')
        return Response(
            content,
            content_type='application/javascript; charset=utf-8',
            headers=[('Cache-Control', 'public, max-age=604800')],
        )
