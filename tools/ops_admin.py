"""SaaS 平台运维账号的命令行工具（在服务器本机上运行；建第一个运维账号、忘了密码/TOTP 时用）。

    python tools/ops_admin.py create --username ops.zhang [--name 张三] [--password …]   不给密码就生成一个（只显示这一次）
    python tools/ops_admin.py reset  --username ops.zhang                               重置密码 + 清掉 TOTP（下次登录重新绑定）
    python tools/ops_admin.py list
    python tools/ops_admin.py verify-audit                                              检查审计哈希链

数据目录和服务一样：设了 VF_HOME 就用那个（例如 VF_HOME=/srv/vf python tools/ops_admin.py …）。每次操作都记进运维审计（admin = cli）。
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ops_admin')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('create')
    c.add_argument('--username', required=True)
    c.add_argument('--name', default='')
    c.add_argument('--password', default='')
    r = sub.add_parser('reset')
    r.add_argument('--username', required=True)
    r.add_argument('--password', default='')
    sub.add_parser('list')
    sub.add_parser('verify-audit')
    a = ap.parse_args(argv)
    from fastapi import HTTPException
    from vfactory import store
    from vfactory.tenancy import ops, security
    store.conn()
    try:
        if a.cmd == 'create':
            pw = ops.create_admin(a.username, a.name, a.password or None, must_change=not a.password)
            ops.audit('cli', 'admin_create', a.username, '命令行', 'localhost')
            print(f'已建运维账号 {a.username}' + ('' if a.password else f'，初始密码：{pw}（只显示这一次，第一次登录要改）'))
            print('第一次登录 /ops 时要用手机验证器 App 扫码绑定 TOTP，并保存 10 个恢复码。')
        elif a.cmd == 'reset':
            row = store.q('select * from ops_admins where username=?', (a.username,), one=True)
            if not row:
                sys.exit(f'没有运维账号 {a.username}')
            pw = a.password or security.random_password(14)
            security.check_password(pw, a.username, strict=True)
            store.x("update ops_admins set pw=?, must_change=?, totp_on=0, totp_secret=null, totp_last=0, recovery='[]', failed=0, locked_until=null, "
                    'active=1 where id=?', (store.hash_pw(pw), 0 if a.password else 1, row['id']))
            store.x('update ops_sessions set revoked=1 where admin=?', (a.username,))
            ops.audit('cli', 'admin_reset', a.username, '命令行：重置密码和 TOTP', 'localhost')
            print(f'已重置 {a.username}' + ('' if a.password else f'，临时密码：{pw}') + '；下次登录重新绑定 TOTP')
        elif a.cmd == 'list':
            for row in store.q('select * from ops_admins order by id'):
                print(json.dumps(ops.admin_view(row), ensure_ascii=False))
        elif a.cmd == 'verify-audit':
            r = ops.verify_chain()
            print(json.dumps(r, ensure_ascii=False, indent=1))
            sys.exit(0 if r['ok'] else 2)
    except HTTPException as e:
        sys.exit(str(e.detail))


if __name__ == '__main__':
    main()
