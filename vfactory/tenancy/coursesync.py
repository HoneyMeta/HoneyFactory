"""SaaS 里老师做课程（5.0）：课程编辑器、出题检查、预览都在老师的客户端本机跑（同一套规则引擎），发布时把签名的课程包传到服务器。

客户端（老师，连着 SaaS 服务器）：
  /api/teach/authoring/…  由本地服务处理（desktop_proxy.route）：草稿、试运行、预览（预览的作业号从 PREVIEW_AID_BASE 起，不和服务器的作业号撞）
  发布 = 本机冻结 + 本机密钥签名的 .vfcourse → POST <服务器>/api/teach/authoring/upload {package, public_key, draft}
  "我做的课程"同时列出服务器上自己的课（别的电脑上做的）：点"下载到本机继续改"→ GET <服务器>/api/teach/authoring/{cid}/draft
服务器（不跑工厂）：
  upload：查包的结构、每个文件的哈希、签名（用随包传来的公钥，key_id 要对得上）、引擎版本、课程的静态校验（不试运行），
          课程编号不能是别人的；通过后存成本单位的老师课程（版本号由服务器递增），学生下载时由服务器用自己的密钥重新签名
          （学生客户端只认服务器的公钥，见 courses/coursepkg.py）。
  draft：可编辑的草稿（含作答题答案，不含参考做法——参考做法只在老师电脑上）；只给课程的主人和本单位管理员。
"""
from ..i18n import _tr
import base64
import copy
import json
import logging
import os
import re

from fastapi import HTTPException

from .. import store

log = logging.getLogger('vfactory.tenancy')
PREVIEW_AID_BASE = 1_000_000_000
CID_RE = re.compile(r'^tc-[0-9a-f]{4,24}$')


# ---------------------------------------------------------------- 客户端这边
def client_saas():
    """本进程是客户端，并且登录着 SaaS 服务器（老师的课程编辑器在本机跑）。"""
    try:
        from ..teach import client as tclient
        if not tclient.is_desktop_proc():
            return False
        s = tclient.load_settings()
        return s.get('deploy') == 'saas' and bool(s.get('url')) and bool(s.get('token'))
    except Exception:                                   # noqa: BLE001
        return False


async def _remote(path, method='GET', body=None, timeout=60):
    from ..teach.client import remote
    return await remote(path, method, body, timeout=timeout)


async def remote_list():
    try:
        r = await _remote('/api/teach/authoring', timeout=15)
        return r if isinstance(r, list) else []
    except HTTPException:
        return []


async def remote_draft(cid):
    return await _remote(f'/api/teach/authoring/{cid}/draft', timeout=30)


async def upload(data: bytes, draft: dict):
    """把本机发布好的课程包传到服务器。→ 服务器的回答 {id, version, …}。连不上抛 502（草稿和本机版本都在）。"""
    from ..courses import coursepkg
    info = coursepkg.public_info()
    if info.get('alg') != 'ed25519':
        raise HTTPException(500, _tr('本机缺少 cryptography 组件，签不了课程包'))
    body = {'package': base64.b64encode(data).decode('ascii'), 'public_key': info['public_key'], 'draft': draft}
    try:
        return await _remote('/api/teach/authoring/upload', 'POST', body, timeout=120)
    except HTTPException as e:
        if e.status_code == 502:
            raise HTTPException(502, _tr('本机已经发布好了，但没传到服务器（{detail}）：联网后再点一次"发布"', detail=e.detail))
        raise


async def remote_package_course(cid):
    """从服务器下课程包（服务器签名，用本机记下的服务器公钥验），返回课程（作答题答案解封，给"复制一份来改"用）。"""
    from ..courses import coursepkg
    from ..teach import client as tclient
    st = tclient.load_settings()
    keys = st.get('course_keys') or {}
    data = await _remote(f'/api/teach/courses/{cid}/package', timeout=60)
    if isinstance(data, dict):
        raise HTTPException(404, _tr('服务器没有这门课的课程包'))
    try:
        d = coursepkg.verify(data, keys)
    except coursepkg.CoursePackageError as e:
        raise HTTPException(400, _tr('课程包校验没通过：{e}', e=e))
    return unseal_course(d['course'])


def unseal_course(c):
    """课程包里封存的作答题答案、解析 → 明文（老师复制课程来改时用；学生客户端从不调用）。"""
    from ..courses import rules as R
    c = copy.deepcopy(c)
    for ch in c.get('chapters') or []:
        for l in ch.get('lessons') or []:
            for r in l.get('rules') or []:
                if r.get('seal') is not None:
                    v = R.answer_of(r, l, c.get('id'))
                    if v is not None:
                        r['answer'] = v
                    r.pop('seal', None)
                if r.get('explain_seal'):
                    e = R.explain_of(r, l, c.get('id'))
                    if e:
                        r['explain'] = e
                    r.pop('explain_seal', None)
    return c


# ---------------------------------------------------------------- 服务器这边
def ingest(u, body):
    """服务器收老师客户端传来的课程包。不跑工厂：结构、哈希、签名、引擎版本、静态校验、归属。→ {id, version, …}。"""
    from .. import courses
    from ..courses import coursepkg, rules as R
    from ..teach import authoring as A
    from . import seats
    try:
        raw = base64.b64decode(str(body.get('package') or ''), validate=True)
        pub = str(body.get('public_key') or '')
        pub_raw = base64.b64decode(pub, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(400, _tr('课程包或公钥不是有效的 base64'))
    if len(raw) > coursepkg.MAX_BYTES:
        raise HTTPException(413, _tr('课程包太大（最多 20 MB）'))
    if len(pub_raw) != 32:
        raise HTTPException(400, _tr('签名公钥不对（Ed25519 公钥是 32 字节）'))
    try:
        d = coursepkg.read(raw)
        kid = coursepkg.key_id(pub_raw)
        if (d['signature'] or {}).get('key_id') != kid or (d['signature'] or {}).get('alg') != 'ed25519':
            raise coursepkg.CoursePackageError(_tr('课程包的签名不是这把公钥签的'))
        coursepkg.check_sig(d['manifest_bytes'], d['signature'], {kid: pub})
    except coursepkg.CoursePackageError as e:
        raise HTTPException(400, _tr('课程包没有通过检查：{e}', e=e))
    man, c = d['manifest'], d['course']
    cid = str(c.get('id') or '')
    if not CID_RE.match(cid):
        raise HTTPException(400, _tr('课程编号不对（老师做的课程编号是 tc- 开头）'))
    try:
        engine = int(man.get('engine') or 0)
    except (TypeError, ValueError):
        engine = 999
    if engine > int(R.RULES_VERSION):
        raise HTTPException(400, _tr('这门课用的评分规则（{get}）比服务器（{RULES_VERSION}）新：请先升级服务器', get=man.get('engine'), RULES_VERSION=R.RULES_VERSION))
    draft = body.get('draft') if isinstance(body.get('draft'), dict) else None
    if draft is not None:
        dl = [(l.get('id'), l.get('kind', 'plant')) for _ch, l in courses.lessons(draft)]
        pl = [(l.get('id'), l.get('kind', 'plant')) for _ch, l in courses.lessons(c)]
        if dl != pl:
            raise HTTPException(400, _tr('草稿和课程包里的课对不上（先在客户端里保存再发布）'))
        if len(json.dumps(draft, ensure_ascii=False)) > 2_000_000:
            raise HTTPException(413, _tr('课程草稿太大了（超过 2 MB）'))
    probe = draft if draft is not None else c
    iss = [i for i in A.validate_course(probe) if i['level'] == 'error' and not i.get('check') and (draft is not None or not ('答案' in i['msg'] or 'answer' in i['msg'].lower()))]
    if iss:
        raise HTTPException(400, _tr('课程还有问题，服务器不收：') + _tr('；').join(f"{i['where']} {i['msg']}" for i in iss[:5]))
    org = u.get('org') or 'default'
    if not seats.feature(org, 'plc') and any(l.get('kind') == 'cell' for _ch, l in courses.lessons(c)):
        raise HTTPException(403, _tr('本单位没有开通 PLC 实训功能包：这门课里有 PLC 编程课'))
    A._ready()
    row = A._row(cid)
    if row is None and courses.get_course(cid):
        raise HTTPException(409, _tr('课程编号 {cid} 已经被用了：请在客户端里"复制一份"再发布', cid=cid))
    if row is not None and row['owner'] != u['username']:
        if not (u.get('role') in ('orgadmin', 'admin') and store.org_of(row['owner']) == org):
            raise HTTPException(409, _tr('课程编号 {cid} 是别人的课程', cid=cid))
    owner = row['owner'] if row else u['username']
    ver = int((row or {}).get('version') or 0) + 1
    frozen = copy.deepcopy(c)
    frozen.update(id=cid, owner=owner, version=ver, origin='authored')
    frozen.pop('package', None)
    A._write_frozen(cid, frozen)
    adir = A._assets_dir(cid)
    os.makedirs(adir, exist_ok=True)
    for n, b in (d['assets'] or {}).items():
        n = os.path.basename(n)
        if n.lower().endswith(coursepkg.ASSET_EXT) and len(b) <= 3 * 1024 * 1024:
            with open(os.path.join(adir, n), 'wb') as fh:
                fh.write(b)
    keep = draft if draft is not None else {k: v for k, v in frozen.items() if k not in ('id', 'owner', 'version', 'origin')}
    now = store.now()
    if row:
        A.db.x('update authored_courses set data=?, version=?, published_at=?, pub_hash=?, updated=? where id=?',
               (json.dumps(keep, ensure_ascii=False), ver, now, man.get('content_sha256'), now, cid))
    else:
        A.db.x('insert into authored_courses(id, owner, data, created, updated, version, published_at, pub_hash) values(?,?,?,?,?,?,?,?)',
               (cid, owner, json.dumps(keep, ensure_ascii=False), now, now, ver, now, man.get('content_sha256')))
    store.audit(u['username'], 'POST', '/api/teach/authoring/upload', 200, _tr('上传课程 {cid} v{ver}（签名 {kid}）', cid=cid, ver=ver, kid=kid), org=org)
    log.info(_tr('收到老师 %s 的课程 %s v%s（%s 课，签名 %s）'), u['username'], cid, ver, len(courses.lessons(c)), kid)
    return {'ok': True, 'id': cid, 'version': ver, 'content_sha256': man.get('content_sha256'), 'lessons': len(courses.lessons(c)),
            'signed_by': kid, 'name': c.get('name')}
