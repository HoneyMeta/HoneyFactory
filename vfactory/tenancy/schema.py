"""5.0 新表和旧库迁移。store.conn() 第一次打开数据库时调用 ensure(conn)（持有 store 的锁，所以这里只用传进来的连接）。

迁移规则（可重复执行，不丢数据）：
- 建"默认单位" default（已有就不动）；
- 已有表里 org 为空的行一律归 default（4.x 的表本来就带 org 列，默认值就是 default）；
- users 补上 archived（归档，不占席位）、failed / locked_until（登录失败锁定）、pw_at（最近改密码时间）。
"""
from ..i18n import _tr
from datetime import datetime

DDL = """
create table if not exists orgs(id text primary key, name text, kind text default 'school', status text default 'active', plan text, contract_no text,
  start_date text, expires text, seats_teachers integer, seats_students integer, features text, ai_quota integer, trial integer default 0,
  contact text, notes text, created text, updated text);
create table if not exists sessions(sid text primary key, username text, org text, created text, expires text, last_seen text, ip text,
  agent text, revoked integer default 0);
create index if not exists ix_sessions_user on sessions(username);
create table if not exists ai_usage(org text, month text, tokens integer default 0, calls integer default 0, primary key(org, month));
create table if not exists progress_reports(username text, assignment_id integer, org text, class_id integer, step text, progress real, score real,
  state text, client_at text, received text, data text, primary key(username, assignment_id));
create table if not exists progress_log(id integer primary key, org text, username text, assignment_id integer, step text, progress real, score real,
  state text, client_at text, received text);
create index if not exists ix_progress_log on progress_log(username, assignment_id);
create table if not exists presence(username text primary key, org text, last_seen text, client text, assignment_id integer, step text);
create table if not exists ops_admins(id integer primary key, username text unique, name text, pw text, totp_secret text, totp_on integer default 0,
  totp_last integer default 0, recovery text, active integer default 1, failed integer default 0, locked_until text, created text, last_login text,
  must_change integer default 0);
create table if not exists ops_sessions(sid text primary key, admin text, csrf text, created real, last_seen real, expires real, ip text,
  revoked integer default 0);
create table if not exists ops_audit(id integer primary key, t text, admin text, action text, target text, detail text, ip text, prev text, hash text);
create trigger if not exists ops_audit_no_update before update on ops_audit begin select raise(abort, 'ops_audit is append-only'); end;
create trigger if not exists ops_audit_no_delete before delete on ops_audit begin select raise(abort, 'ops_audit is append-only'); end;
create table if not exists ops_settings(k text primary key, v text);
"""
USER_COLS = (('archived', 'integer default 0'), ('failed', 'integer default 0'), ('locked_until', 'text'), ('pw_at', 'text'))
ORG_TABLES = ('users', 'tokens', 'audit', 'scenarios', 'experiments', 'assistant_threads', 'classes', 'assignments')
DEFAULT_ORG = 'default'


def ensure(c):
    c.executescript(DDL)
    have = {r[1] for r in c.execute('pragma table_info(users)').fetchall()}
    for name, typ in USER_COLS:
        if name not in have:
            c.execute(f'alter table users add column {name} {typ}')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("insert or ignore into orgs(id, name, kind, status, created, updated) values(?,?,?,?,?,?)",
              (DEFAULT_ORG, _tr('默认单位'), 'school', 'active', now, now))
    migrate_orgs(c)
    c.commit()


def migrate_orgs(c):
    """已有表里没有单位的行归默认单位（教学表是 teach/db.py 后建的，那边建表后也会调一次）。"""
    tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'").fetchall()}
    for t in ORG_TABLES:
        if t in tables:
            cols = {r[1] for r in c.execute(f'pragma table_info({t})').fetchall()}
            if 'org' in cols:
                c.execute(f"update {t} set org=? where org is null or org=''", (DEFAULT_ORG,))
