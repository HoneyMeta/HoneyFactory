"""把构建好的客户端（tools/build_electron.ps1 的 dist-electron/）发布成服务器上的自动更新（vfactory/client_update.py）。

    python tools/publish_client_update.py                                   # 发到本机服务器的数据目录 data/client-updates/（服务器和仓库在同一台机器）
    python tools/publish_client_update.py --to-dir D:/vf-data/client-updates # 发到指定目录（例如 Docker 挂载的数据目录）
    python tools/publish_client_update.py --server http://192.168.1.10:8800 --user admin   # 通过接口上传（管理员账号，密码会问；或环境变量 VF_ADMIN_TOKEN）
    python tools/publish_client_update.py --list --server …                 # 看服务器上现在放着什么

发的是 latest.yml 里写的那个安装包（HoneyVF-Setup-<版本>.exe）和它的 .blockmap；latest.yml 最后发（客户端看到新版本号时安装包已经在了）。
已经连着这台服务器的客户端在启动时和每 6 小时检查一次，后台下载，下好后问"现在重启更新 / 下次启动时"。
"""
import argparse
import getpass
import json
import os
import re
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_latest(path):
    text = open(path, encoding='utf-8').read()
    ver = re.search(r'^version:\s*[\'"]?([^\'"\s]+)', text, re.M)
    exe = re.search(r'^path:\s*[\'"]?([^\'"\n]+?)[\'"]?\s*$', text, re.M)
    if not ver or not exe:
        sys.exit(f'{path} 里没有 version / path，不像 electron-builder 生成的 latest.yml')
    return ver.group(1), exe.group(1).strip()


def req(method, url, token='', data=None, ctype='application/octet-stream'):
    h = {'Authorization': 'Bearer ' + token} if token else {}
    if data is not None:
        h['Content-Type'] = ctype
    r = urllib.request.Request(url, method=method, data=data, headers=h)
    with urllib.request.urlopen(r, timeout=1800) as f:
        return json.loads(f.read() or b'{}')


def main():
    ap = argparse.ArgumentParser(description='发布客户端自动更新')
    ap.add_argument('--dist', default=os.path.join(ROOT, 'dist-electron'))
    ap.add_argument('--to-dir', default='', help='直接拷到这个目录（默认：仓库的 data/client-updates）')
    ap.add_argument('--server', default='', help='通过接口上传到这台服务器（管理员）')
    ap.add_argument('--user', default='admin')
    ap.add_argument('--list', action='store_true', help='只列出服务器上现有的文件')
    a = ap.parse_args()

    token = ''
    if a.server:
        a.server = a.server.rstrip('/')
        token = os.environ.get('VF_ADMIN_TOKEN', '')
        if not token:
            pw = getpass.getpass(f'{a.server} 的 {a.user} 密码：')
            token = req('POST', a.server + '/api/login', data=json.dumps({'username': a.user, 'password': pw}).encode(), ctype='application/json')['token']
        if a.list:
            print(json.dumps(req('GET', a.server + '/api/admin/client-update', token), ensure_ascii=False, indent=1))
            return

    latest = os.path.join(a.dist, 'latest.yml')
    if not os.path.isfile(latest):
        sys.exit(f'没有 {latest}：先运行 tools\\build_electron.ps1')
    ver, exe = parse_latest(latest)
    files = [exe, exe + '.blockmap', 'latest.yml']
    if not os.path.isfile(os.path.join(a.dist, exe)):
        sys.exit(f'latest.yml 说的安装包 {exe} 不在 {a.dist}')
    files = [f for f in files if os.path.isfile(os.path.join(a.dist, f))]
    print(f'发布客户端 {ver}：{", ".join(files)}')
    if a.server:
        for f in files:
            with open(os.path.join(a.dist, f), 'rb') as fh:
                r = req('PUT', f'{a.server}/api/admin/client-update/{f}', token, data=fh.read())
            print(f'  已上传 {f}（{r.get("size", 0) / 1024 / 1024:.1f} MB）')
        print(f'完成：{a.server}/api/client/update/latest.yml → {ver}')
        return
    dst = a.to_dir or os.path.join(ROOT, 'data', 'client-updates')
    os.makedirs(dst, exist_ok=True)
    for f in files:
        shutil.copyfile(os.path.join(a.dist, f), os.path.join(dst, f + '.part'))
        os.replace(os.path.join(dst, f + '.part'), os.path.join(dst, f))
        print(f'  已拷贝 {f}')
    print(f'完成：{dst}（服务器的 /api/client/update/latest.yml → {ver}）')


if __name__ == '__main__':
    main()
