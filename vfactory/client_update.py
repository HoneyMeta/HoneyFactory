"""客户端（Electron）自动更新的下载源：服务器把新版安装包放在 data/client-updates/，客户端连着哪台服务器就从哪台更新（设计 4.5）。

    GET  /api/client/update/latest.yml          electron-updater（generic 提供方）读的版本说明：version、path、sha512、size
    GET  /api/client/update/<文件>               安装包（HoneyVF-Setup-<版本>.exe）和 .blockmap（增量下载用）
    GET  /api/admin/client-update               管理员：现在放着哪些文件、对外的版本号
    PUT  /api/admin/client-update/<文件>         管理员：上传一个文件（请求体就是文件内容）。先传安装包和 .blockmap，最后传 latest.yml
    DELETE /api/admin/client-update/<文件>       管理员：删掉一个文件

前两个不要登录（electron-updater 下载时不带令牌）；只发这个目录里的文件，文件名只能是字母、数字、点、横线、下划线。
命令行：python tools/publish_client_update.py（把 dist-electron 里的安装包发布到本机目录或远程服务器）。
"""
from .i18n import _tr
import os
import re

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from . import paths

OPEN_PREFIXES = ('/api/client/update/',)
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$')
MAX_BYTES = 800 * 1024 * 1024


def updates_dir():
    return paths.data('client-updates')


def _safe(name):
    if not NAME.match(name or '') or '..' in name:
        raise HTTPException(400, _tr('文件名只能用字母、数字、点、横线、下划线'))
    return os.path.join(updates_dir(), name)


def latest_version():
    """latest.yml 里的 version（不用 yaml 库：只取这一行）。"""
    try:
        with open(os.path.join(updates_dir(), 'latest.yml'), encoding='utf-8') as f:
            for line in f:
                m = re.match(r'^version:\s*[\'"]?([^\'"\s]+)', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def register(app, mgr=None):
    def admin(request: Request):
        u = getattr(request.state, 'user', None)
        if not u or u.get('role') != 'admin':
            raise HTTPException(403, _tr('只有管理员能管理客户端更新'))

    @app.get('/api/client/update/{name}', include_in_schema=False)
    async def update_file(name: str):
        p = _safe(name)
        if not os.path.isfile(p):
            raise HTTPException(404, _tr('服务器上没有放客户端更新') if name == 'latest.yml' else _tr('没有这个文件：{name}', name=name))
        headers = {'Cache-Control': 'no-cache'} if name.endswith('.yml') else {}
        media = 'text/yaml; charset=utf-8' if name.endswith('.yml') else 'application/octet-stream'
        return FileResponse(p, media_type=media, headers=headers)

    @app.get('/api/admin/client-update')
    async def list_updates(request: Request):
        admin(request)
        d = updates_dir()
        files = []
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            st = os.stat(os.path.join(d, f))
            files.append({'name': f, 'size': st.st_size, 'mtime': int(st.st_mtime)})
        return {'dir': d, 'version': latest_version(), 'files': files, 'feed': '/api/client/update/'}

    @app.put('/api/admin/client-update/{name}')
    async def upload_update(name: str, request: Request):
        admin(request)
        p = _safe(name)
        os.makedirs(updates_dir(), exist_ok=True)
        tmp, n = p + '.part', 0
        try:
            with open(tmp, 'wb') as f:
                async for chunk in request.stream():
                    n += len(chunk)
                    if n > MAX_BYTES:
                        raise HTTPException(413, _tr('文件太大'))
                    f.write(chunk)
            if not n:
                raise HTTPException(400, _tr('收到的文件是空的'))
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return {'ok': True, 'name': name, 'size': n, 'version': latest_version()}

    @app.delete('/api/admin/client-update/{name}')
    async def delete_update(name: str, request: Request):
        admin(request)
        p = _safe(name)
        if os.path.isfile(p):
            os.remove(p)
        return {'ok': True}
