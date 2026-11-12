"""Pin a Python test to a UI language (import it at the top of the test).

The server picks the language of each request from the `X-Lang` header (vfactory/i18n.py). Tests that assert Chinese texts
import this module: every HTTP request made with urllib / http.client then carries `X-Lang: <VF_TEST_LANG or zh-CN>`, and code
of the product run inside the test process (offline checks) uses the same language (VF_LANG).

    VF_TEST_LANG=en python tests/api_check.py      # run a suite in English (only meaningful for suites that do not assert texts)
"""
import http.client
import os

LANG = os.environ.get('VF_TEST_LANG') or 'zh-CN'
os.environ.setdefault('VF_LANG', LANG)

if not getattr(http.client.HTTPConnection, '_vf_lang_pinned', False):
    _orig_putrequest = http.client.HTTPConnection.putrequest
    _orig_endheaders = http.client.HTTPConnection.endheaders
    _orig_putheader = http.client.HTTPConnection.putheader

    def putrequest(self, *a, **kw):
        self._vf_has_lang = False
        return _orig_putrequest(self, *a, **kw)

    def putheader(self, header, *values):
        if str(header).lower() == 'x-lang':
            self._vf_has_lang = True
        return _orig_putheader(self, header, *values)

    def endheaders(self, *a, **kw):
        if not getattr(self, '_vf_has_lang', True):
            _orig_putheader(self, 'X-Lang', LANG)
            self._vf_has_lang = True
        return _orig_endheaders(self, *a, **kw)

    http.client.HTTPConnection.putrequest = putrequest
    http.client.HTTPConnection.putheader = putheader
    http.client.HTTPConnection.endheaders = endheaders
    http.client.HTTPConnection._vf_lang_pinned = True
