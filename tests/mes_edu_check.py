"""本机 MES（蜂元教学 MES，本仓库 vfmes/，4.6；5.0.1 页面并进虚拟工厂、取数走本地服务的 /api/mes/* 转发）接口测试：
客户端本地服务 → 给本机工厂按需启动 MES → 经 /api/mes/* 转发：采集、工单、报工、OEE、追溯 → 评分取数 → 空闲自动停止 → 退出。

自己起一个客户端本地服务（python -m vfactory desktop，临时数据目录，单机模式），不碰别的实例：
    python tests/mes_edu_check.py [运行秒数，默认 90]
MES 就在本仓库（vfmes\\；页面在 web/src/mes/，不用另外构建）。环境变量：VF_ENTRY（启动脚本，B 机测试副本用 run_me.py）、
          VF_TEST_CLIENT_PORT（默认 8880）、VF_TEST_OPCUA / VF_TEST_MQTT / VF_TEST_MODBUS（默认 4920 / 1964 / 6700）、VF_MES_PORT（MES 端口，默认自动）、
          VF_TEST_KEEP=1 保留临时目录。
覆盖：MES 进程用的是本仓库的 vfmes（不是 HoneyMES）；没有 AI（问数、日报、异常解释、知识库、助手、智能体/审批、AI 报告、配料优化、缺陷回溯/协同排产 → 404；菜单实体里没有；刀具只有寿命计数）；
只给本机工厂（不存在的工厂 404）；协议只给这个工厂打开；一次性登录票（本地服务内部用）；转发 /api/mes/*（要虚拟工厂的登录、
下载用 ?token=、MES 的钥匙和会话令牌不出本地服务、MES 停了回 503）；自动导入设备；下工单 → 下达 → 加速仿真 → 自动报工、工单生产中、OEE、一件一码追溯、SPC；
评分取数（/api/edu/check、snapshot、vfactory.mes.teach_rules 的取数函数、MES 入门课 m01 评分）；空闲自动停止、重开后数据还在；停止、本地服务退出时 MES 跟着退出。
"""
import os as _os, sys as _sys  # noqa: E401
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import i18n_pin  # noqa: E402,F401  (X-Lang: zh-CN on every request unless VF_TEST_LANG is set; see tests/i18n_pin.py)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_S = int(sys.argv[1]) if len(sys.argv) > 1 else 90
PORT = int(os.environ.get('VF_TEST_CLIENT_PORT', '8880'))
WORK = tempfile.mkdtemp(prefix='vf-mes-')
HOME = os.path.join(WORK, 'home')
results = []


def ok(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name, str(detail)[:300], flush=True)


def req(method, url, body=None, token='', headers=None, timeout=60):
    h = {'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + token} if token else {}), **(headers or {})}
    r = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(r, timeout=timeout) as f:
            raw = f.read()
            try:
                return f.status, json.loads(raw)
            except ValueError:
                return f.status, raw.decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def port_open(p):
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(('127.0.0.1', p)) == 0
    finally:
        s.close()


def main():
    if not os.path.isfile(os.path.join(ROOT, 'vfmes', '__main__.py')):
        print('没有蜂元教学 MES：', os.path.join(ROOT, 'vfmes'))
        sys.exit(2)
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    env.pop('VF_MES_SOURCE', None)                   # 4.6 的旧变量（指向 HoneyMES 仓库），已不用
    entry = os.environ.get('VF_ENTRY')
    cmd = [sys.executable] + ([entry] if entry else ['-m', 'vfactory']) + [
        'desktop', '--port', str(PORT), '--home', HOME, '--opcua', os.environ.get('VF_TEST_OPCUA', '4920'),
        '--mqtt', os.environ.get('VF_TEST_MQTT', '1964'), '--modbus', os.environ.get('VF_TEST_MODBUS', '6700')]
    os.makedirs(HOME, exist_ok=True)
    log = open(os.path.join(WORK, 'desktop.log'), 'w', encoding='utf-8')  # noqa: SIM115
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    B = f'http://127.0.0.1:{PORT}'
    try:
        run(B, proc)
    finally:
        try:
            info = json.load(open(os.path.join(HOME, 'run.json'), encoding='utf-8'))
            req('POST', B + '/api/desktop/shutdown', {}, headers={'x-vf-key': info['key']}, timeout=5)
        except Exception:                        # noqa: BLE001
            pass
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        bad = [n for n, g in results if not g]
        print(f"\n{len(results) - len(bad)}/{len(results)} 通过" + ('；失败：' + '、'.join(bad) if bad else ''))
        if os.environ.get('VF_TEST_KEEP') != '1':
            shutil.rmtree(WORK, ignore_errors=True)
        else:
            print('临时目录：', WORK)
        sys.exit(1 if bad else 0)


def run(B, proc):
    t0 = time.time()
    while time.time() - t0 < 180 and not os.path.exists(os.path.join(HOME, 'run.json')):
        if proc.poll() is not None:
            ok('本地服务启动', False, f'退出码 {proc.returncode}')
            return
        time.sleep(0.5)
    info = json.load(open(os.path.join(HOME, 'run.json'), encoding='utf-8'))
    st, s = req('POST', B + '/api/desktop/standalone', {})
    tok = s.get('token', '') if isinstance(s, dict) else ''
    ok('单机模式登录', st == 200 and tok, st)
    st, h = req('GET', B + '/api/health')
    ok('健康检查带 MES 状态', isinstance(h, dict) and (h.get('mes') or {}).get('state') == 'stopped', h.get('mes') if isinstance(h, dict) else h)

    st, m = req('GET', B + '/api/desktop/mes', token=tok)
    plants = m.get('plants') or []
    ok('MES 可用、列出本机工厂', st == 200 and m.get('available') and plants, [(p['id'], p['fit']) for p in plants])
    pid = next((p['id'] for p in plants if p['fit']), plants[0]['id'] if plants else '')
    ok('示范工厂标为推荐', any(p['fit'] for p in plants), pid)
    st, _ = req('POST', B + '/api/desktop/mes/start', {'pid': 'no-such-plant'}, token=tok)
    ok('不是本机工厂不能开 MES', st == 404, st)
    st, h = req('GET', B + '/api/health')
    ok('协议总开关仍是关的', isinstance(h, dict) and h.get('protocols') is False, h.get('protocols') if isinstance(h, dict) else '')

    if os.environ.get('VF_TEST_RAW') == '1':        # 5.0：原始现场模式下教学 MES 照样能接（按点表地址收数）
        st, r = req('PUT', B + f'/api/p/{pid}/delivery/raw_site', {'on': True}, token=tok)
        ok('原始现场模式打开（教学 MES 要照常工作）', st == 200 and r.get('on') is True, r)

    t1 = time.time()
    st, s = req('POST', B + '/api/desktop/mes/start', {'pid': pid}, token=tok, timeout=150)
    ok('启动 MES', st == 200 and s.get('state') == 'running', f"{st} {time.time() - t1:.1f} 秒 {s.get('detail') or s.get('port')}")
    if st != 200:
        return
    M = f"http://127.0.0.1:{s['port']}"
    P = B + '/api/mes'                                   # 5.0.1：页面取数走本地服务的转发

    def mq(method, path, body=None, **kw):
        """经本地服务转发访问 MES：path 写 MES 的接口路径（/api/...）。"""
        return req(method, P + path[4:], body, token=tok, **kw)
    ok('MES 只听本机、端口不是正式版的', s['port'] not in (8900, 8800), s['port'])
    ok('只这个工厂打开了 MQTT', s['ports'].get('mqtt') and s['ports']['mqtt'] != 1883, s['ports'])
    cur = json.load(open(os.path.join(HOME, 'mes', 'current.json'), encoding='utf-8'))
    ok('current.json（评分取数用）', cur.get('pid') == pid and cur.get('port') == s['port'], {k: cur[k] for k in ('pid', 'port')})
    ok('数据在客户端数据目录（每个工厂一份）', os.path.exists(os.path.join(HOME, 'mes', pid.replace('/', '_'), 'mes.db')), os.listdir(os.path.join(HOME, 'mes')))

    # ---------- 登录票（5.0.1：只在本地服务内部用，网页拿不到）----------
    ok('启动结果里没有内嵌地址、钥匙和令牌', 'open_url' not in s and cur['key'] not in json.dumps(s) and 'token' not in s, sorted(s)[:12])
    st, tk = req('POST', M + '/api/edu/ticket', {}, headers={'x-hm-key': cur['key']})
    ticket = tk.get('ticket', '')
    ok('有钥匙换得到一次性登录票', st == 200 and ticket, st)
    st, sess = req('POST', M + '/api/edu/session', {'ticket': ticket})
    mt = sess.get('token', '')
    ok('登录票换本机学员会话', st == 200 and mt and sess['user']['username'] == 'learner', sess.get('user'))
    st, _ = req('POST', M + '/api/edu/session', {'ticket': ticket})
    ok('登录票只能用一次', st == 401, st)
    st, _ = req('POST', M + '/api/login', {'username': 'admin', 'password': 'honey123'})
    ok('没有能用密码登录的账号（演示账号不存在或停用）', st == 401, st)
    st, _ = req('POST', M + '/api/edu/ticket', {})
    ok('没有钥匙换不到登录票', st == 403, st)

    # ---------- 转发 /api/mes/*（5.0.1）----------
    st, me0 = mq('GET', '/api/me')
    ok('转发：本机学员的会话（页面不用登录 MES）', st == 200 and me0.get('username') == 'learner' and me0.get('edu') is True, me0.get('username'))
    st, _ = req('GET', P + '/me')
    ok('转发要虚拟工厂的登录（没有令牌 401）', st == 401, st)
    st, _ = req('GET', P + '/me', token='not-a-token')
    ok('转发：令牌不对 401', st == 401, st)
    st, ei = mq('GET', '/api/edu/info')
    ok('转发：品牌、本机工厂', st == 200 and ei.get('plant', {}).get('id') == pid, ei.get('plant'))
    st, _ = mq('GET', '/api/edu/status')
    ok('转发不带 MES 钥匙（钥匙才能用的接口 403）', st == 403, st)
    st, _ = mq('POST', '/api/edu/ticket', {})
    ok('转发换不到登录票', st == 403, st)
    st, ms0 = req('GET', B + '/api/desktop/mes', token=tok)
    st2, h0 = req('GET', B + '/api/health')
    blob = json.dumps(ms0) + json.dumps(h0)
    ok('状态和健康检查里没有 MES 的钥匙、令牌、内嵌地址', cur['key'] not in blob and mt not in blob and '#edu=' not in blob and 'open_url' not in blob, len(blob))
    st, nf = mq('GET', '/api/nothing/here')
    ok('转发：MES 的 404 原样回来', st == 404, st)
    st, _ = mq('GET', '/api/e/equipment?size=1&token=' + tok + '&vfp=x')
    ok('转发：去掉 token / vfp 查询参数（下载链接用）', st == 200, st)

    # ---------- 跑的是本仓库的 vfmes ----------
    st, est = req('GET', M + '/api/edu/status', headers={'x-hm-key': cur['key']})
    ok('MES 进程用本仓库的 vfmes', st == 200 and os.path.normcase(est.get('source') or '') == os.path.normcase(os.path.join(ROOT, 'vfmes')), est.get('source'))
    ok('MES 进程里没有 honeymes（没加载、sys.path 里也没有 HoneyMES）', est.get('honeymes_loaded') is False and est.get('honeymes_paths') == [],
       {k: est.get(k) for k in ('honeymes_loaded', 'honeymes_paths')})

    # ---------- 没有 AI ----------
    st, info = req('GET', M + '/api/edu/info')
    ok('品牌：蜂元教学 MES', info.get('edu') and info.get('brand') == '蜂元教学 MES', info.get('brand'))
    ai = [('POST', '/api/ai/ask', {'q': '产量'}), ('POST', '/api/ai/daily', {}), ('GET', '/api/ai/status', None), ('GET', '/api/ai/explain/1', None),
          ('POST', '/api/ai/kb_ask', {'q': 'x'}), ('GET', '/api/assistant/threads', None), ('POST', '/api/assistant/chat', {}), ('GET', '/api/agents', None),
          ('GET', '/api/agents/meta', None), ('GET', '/api/approvals/count', None), ('GET', '/api/cross/backtrace', None), ('GET', '/api/cross/coplan', None),
          ('POST', '/api/foundry/optimize', {}), ('GET', '/api/e/kb_doc', None), ('GET', '/api/e/daily_report', None), ('GET', '/api/e/ai_report', None),
          ('GET', '/api/e/schedule_proposal', None), ('POST', '/api/e/report_8d/1/do/ai_draft', {}), ('GET', '/api/notices', None),
          ('GET', '/api/nothing/here', None), ('POST', '/api/nothing/here', {})]
    codes = {p: mq(mth, p, b)[0] for mth, p, b in ai}
    ok('AI 接口、未知接口全部 404', all(c == 404 for c in codes.values()), {p: c for p, c in codes.items() if c != 404} or len(codes))
    st, meta = mq('GET', '/api/meta')
    names = {e['name'] for e in meta.get('entities', [])}
    mods = {e['module'] for e in meta.get('entities', [])}
    ok('菜单实体里没有 AI', meta.get('edu') and 'AI 助手' not in mods and not names & {'kb_doc', 'daily_report', 'ai_report', 'schedule_proposal'}
       and not any('ai_draft' in (e.get('actions') or {}) for e in meta['entities']), sorted(mods))
    ok('保留的核心模块', {'work_order', 'report', 'part', 'ncr', 'equipment', 'stock', 'insp_record', 'repair_order'} <= names, len(names))
    st, me = mq('GET', '/api/me')
    ok('/api/me 带 edu', me.get('edu') is True and me.get('company'), me.get('company'))
    st, home = mq('GET', '/api/dash/home')
    ok('看板（没有大模型、没有日报）', st == 200 and 'llm' not in home and 'report' not in home and home.get('kpi'), home.get('todo'))

    # ---------- 自动导入 ----------
    eqn = 0
    for _ in range(60):
        st, es = mq('GET', '/api/e/equipment?size=100')
        eqn = es.get('total', 0)
        if eqn >= 10:
            break
        time.sleep(1)
    ok('第一次启动自动导入设备', eqn >= 10, f'{eqn} 台')
    st, ds = mq('GET', '/api/e/datasource?f_code=VF')
    d0 = (ds.get('items') or [{}])[0]
    ok('数据源指向这个工厂的 MQTT', d0.get('endpoint') == f"mqtt://127.0.0.1:{s['ports']['mqtt']}" and d0.get('prefix') == f'vfactory/{pid}/', (d0.get('endpoint'), d0.get('prefix')))
    st, tools = mq('GET', '/api/machining/tools')
    ok('刀具：只有寿命计数，没有 AI 估计', tools.get('tools') and all('est' not in t and 'wear_pct' not in t and 'life_pct' in t for t in tools['tools']), f"{len(tools.get('tools', []))} 把")
    st, sys_ = mq('GET', '/api/collector')
    ok('采集已连接', any('已连接' in v for v in (sys_.get('status') or {}).values()), sys_.get('status'))

    # ---------- 下工单 → 仿真 → 报工 / OEE / 追溯 ----------
    st, mats = mq('GET', '/api/e/material?f_code=SGH-450')
    prod = mats['items'][0]
    st, rts = mq('GET', '/api/e/route?size=5')
    st, wo = mq('POST', '/api/e/work_order', {'product': prod['id'], 'route': rts['items'][0]['id'], 'qty': 30, 'priority': 1, 'customer': '实训',
                                                  'due': time.strftime('%Y-%m-%d', time.localtime(time.time() + 5 * 86400))})
    wid = wo.get('id')
    ok('新建工单', st == 200 and wid, wo)
    st, r = mq('POST', f'/api/e/work_order/{wid}/do/release', {})
    ok('下达工单', st == 200, r)
    st, sim = req('POST', B + f'/api/p/{urllib.parse.quote(pid)}/sim', {'speed': 60, 'paused': False}, token=tok)
    ok('虚拟工厂 60× 运行', st == 200, st)
    print(f'仿真 60× 运行 {RUN_S} 秒…', flush=True)
    t2 = time.time()
    while time.time() - t2 < RUN_S:
        time.sleep(10)
        req('POST', B + '/api/desktop/mes/ping', {}, token=tok)
    req('POST', B + f'/api/p/{urllib.parse.quote(pid)}/sim', {'speed': 10}, token=tok)
    st, w = mq('GET', f'/api/e/work_order/{wid}')
    wst = (w.get('item') or w).get('status')
    ok('工单进入生产中', wst in ('in_progress', 'completed'), wst)
    st, rep = mq('GET', '/api/e/report?size=3')
    ok('设备自动报工', rep.get('total', 0) > 0, f"{rep.get('total')} 条")
    st, parts = mq('GET', '/api/e/part?size=1')
    ok('一件一码', parts.get('total', 0) > 10, f"{parts.get('total')} 件")
    st, oee = mq('GET', '/api/equipment/oee?hours=2')
    ok('OEE', len(oee.get('rows', [])) >= 5 and all(0 <= x['OEE'] <= 1 for x in oee['rows']), ', '.join(f"{x['code']} {x['OEE']:.2f}" for x in oee.get('rows', [])[:6]))
    st, pl = mq('GET', '/api/e/part?size=20')
    sn = next((x['sn'] for x in pl.get('items', []) if x.get('heat') or x.get('machine')), (pl.get('items') or [{}])[0].get('sn'))
    st, tr = mq('GET', f'/api/trace/part/{urllib.parse.quote(sn or "x")}')
    ok('单件追溯', st == 200 and tr.get('events'), f"{sn}：{len(tr.get('events') or [])} 个事件，炉次 {(tr.get('part') or {}).get('heat')}，机床 {(tr.get('part') or {}).get('machine')}")
    st, spc = mq('GET', '/api/quality/spc?char=BORE_DIA')
    st, csv = req('GET', P + '/e/work_order.csv?token=' + urllib.parse.quote(tok))
    ok('转发下载：工单导出 CSV（?token=）', st == 200 and isinstance(csv, str) and csv.count('\n') >= 1, (st, str(csv)[:80]))
    st, pr = req('GET', P + f'/trace/part/{urllib.parse.quote(sn or "x")}/print?token=' + urllib.parse.quote(tok))
    ok('转发下载：追溯打印页（HTML）', st == 200 and isinstance(pr, str) and '<' in pr, (st, str(pr)[:60]))
    ok('SPC 有数据', st == 200 and spc.get('count', 0) > 0, f"n={spc.get('count')} Cpk={spc.get('Cpk')}")
    st, ms = req('GET', B + '/api/desktop/mes', token=tok)
    ok('状态里有数据量和空闲时间', ms.get('counts', {}).get('report', 0) > 0 and ms.get('idle_s') is not None, (ms.get('counts'), ms.get('idle_s')))

    # ---------- 评分取数 ----------
    K = {'x-hm-key': cur['key']}
    st, c1 = req('POST', M + '/api/edu/check', {'query': 'work_order.count', 'where': {'product': 'SGH-450', 'status': ['in_progress', 'completed'], 'qty_gte': 20}}, headers=K)
    ok('检查：生产中的 SGH-450 工单', st == 200 and c1.get('value', 0) >= 1, c1)
    st, c2 = req('POST', M + '/api/edu/check', {'query': 'oee.worst'}, headers=K)
    worst = c2.get('value')
    ok('检查：OEE 最差的设备', st == 200 and worst, worst)
    st, c3 = req('POST', M + '/api/edu/check', {'query': 'repair.for_worst_oee', 'where': {'hours': 2, 'rank': 2}}, headers=K)
    ok('检查：还没给最差设备报修 = 0', c3.get('value') == 0, c3)
    eq = next(e for e in mq('GET', '/api/e/equipment?size=100')[1]['items'] if e['code'] == worst)
    st, ro = mq('POST', '/api/e/repair_order', {'equipment': eq['id'], 'fault': 'OEE 最低，停机多'})
    st, c3 = req('POST', M + '/api/edu/check', {'query': 'repair.for_worst_oee', 'where': {'hours': 2, 'rank': 2}}, headers=K)
    ok('检查：报修后 = 1', c3.get('value') == 1, c3)
    st, c4 = req('POST', M + '/api/edu/check', {'query': 'spc.stable', 'where': {'char': 'BORE_DIA'}, 'answer_key': 'stable', 'answers': {'stable': True}}, headers=K)
    ok('检查：SPC 判断核对（0/1 或数据不够）', st == 200 and c4.get('value') in (0, 1, None), c4)
    st, c5 = req('POST', M + '/api/edu/check', {'query': 'no.such'}, headers=K)
    ok('不认识的检查 400', st == 400, st)
    st, c6 = req('POST', M + '/api/edu/check', {'query': 'ncr.count'})
    ok('检查要钥匙或登录', st == 401, st)
    # 课程评分（K 的规则引擎 + 本模块的取数函数），在本进程里按客户端的数据目录取 current.json
    os.environ['VF_HOME'] = HOME
    sys.path.insert(0, ROOT)
    from vfactory.courses import get_lesson, score_job
    from vfactory.mes import teach_rules
    c, l = get_lesson('mes_intro', 'm01')
    ok('MES 入门课程（4 课）', c and l and len(c['chapters'][0]['lessons']) == 4, c and c.get('name'))
    snap = teach_rules.snapshot(l['rules'], {'q_status': 1}, pid)
    ok('快照（交作业时带上）', snap.get('wo', 0) >= 1 and snap.get('rep', 0) >= 1, snap)
    sc = score_job('mes_intro', 'm01', {'username': 'local'}, {'q_status': 1})
    ok('m01 评分（本机 MES 取数）', sc.get('ok') and sc.get('score') == sc.get('max'), f"{sc.get('score')}/{sc.get('max')} " + '；'.join(d['text'] for d in sc.get('details', [])))
    sc2 = score_job('mes_intro', 'm02', {'username': 'local'}, {'q_oee': 0.684, 'q_loss': 0})
    ok('m02 评分（给最差设备报了修）', sc2.get('ok') and sc2.get('score') == sc2.get('max'), f"{sc2.get('score')}/{sc2.get('max')}")
    sc3 = score_job('mes_intro', 'm01', {'username': 'local', 'mes_snapshot': {'wo': 0, 'rep': 0}}, {'q_status': 1})
    ok('按快照复评（服务器上没有 MES 时）', sc3.get('score') == 30, sc3.get('score'))

    # ---------- 空闲自动停止、重开数据还在 ----------
    st, _ = req('PUT', B + '/api/desktop/mes/settings', {'idle_min': 0.05}, token=tok)
    stopped = None
    for _ in range(40):
        time.sleep(1)
        st, ms = req('GET', B + '/api/desktop/mes', token=tok)
        if ms.get('state') == 'stopped':
            stopped = ms
            break
    ok('空闲自动停止', stopped and '空闲' in (stopped.get('stopped_why') or ''), (stopped or {}).get('stopped_why'))
    ok('停止后 MES 端口关闭、current.json 删除', not port_open(s['port']) and not os.path.exists(os.path.join(HOME, 'mes', 'current.json')), s['port'])
    st, x503 = mq('GET', '/api/me')
    ok('MES 停了：转发回 503（页面换成"已停止"）', st == 503 and x503.get('mes_state') == 'stopped', (st, x503))
    st, ms1 = req('GET', B + '/api/desktop/mes', token=tok)
    ok('记住上次用的工厂（下次打开 MES 页面自动启动它）', ms1.get('last_pid') == pid, ms1.get('last_pid'))
    sc4 = score_job('mes_intro', 'm01', {'username': 'local'}, {'q_status': 1})
    ok('MES 没在跑：MES 规则判"没有连上"', sc4.get('score') == 30 and 'MES' in ' '.join(d['text'] for d in sc4['details']), sc4.get('score'))
    req('PUT', B + '/api/desktop/mes/settings', {'idle_min': 30}, token=tok)
    st, s2 = req('POST', B + '/api/desktop/mes/start', {'pid': pid}, token=tok, timeout=150)
    st, w2 = mq('GET', f'/api/e/work_order/{wid}')
    ok('重开 MES，工单还在（转发换了新会话）', st == 200, (w2.get('item') or w2).get('code'))
    mes_proc = s2.get('process')

    # ---------- 退出 ----------
    st, x = req('POST', B + '/api/desktop/mes/stop', {}, token=tok)
    ok('停止 MES', st == 200 and x.get('state') == 'stopped' and not port_open(s2['port']), x.get('stopped_why'))
    st, s3 = req('POST', B + '/api/desktop/mes/start', {'pid': pid}, token=tok, timeout=150)
    mp = s3.get('port')
    req('POST', B + '/api/desktop/shutdown', {}, headers={'x-vf-key': info['key']}, timeout=5)
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(3)
    ok('本地服务退出时 MES 跟着退出', proc.poll() is not None and mp and not port_open(mp), (proc.poll(), mp, mes_proc))


if __name__ == '__main__':
    main()
