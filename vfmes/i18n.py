"""Teaching MES i18n: the same language rules and catalogue as the Virtual Factory (vfactory/i18n.py, vfactory/locale/en.json).

The MES runs as a separate process started by the desktop client; it inherits VF_LANG, and the client forwards the page's
`X-Lang` header with every proxied request (vfactory/mes/sidecar.py).
"""
from vfactory.i18n import (_tr, content, default_lang, en_text, install, is_zh, label, lang, llm_instruction, matches, tr,  # noqa: F401
                           tr_obj, use, variants)
