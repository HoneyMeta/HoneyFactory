"""作业包 .vfhw（设计 4.2 第 4 节）：客户端离线做的作业，联网提交或导出文件交给老师。

zip 内容：
  manifest.json      {format:'vfhw', version:1|2, client_version, created, student:{username,name}, server, assignment_id, course, lesson, scene,
                      kind: cell|plant|diagnose|factory, local_score:{score,max,details}, files:[...], sha256:{文件: 哈希}}
                     版本 2（4.4）多了 kind=factory（"提交工厂"作业：学生在客户端"我的工厂"里建的整座工厂）和 plant:{id, name, blocks, plcs}。
  program/<编号>.json PLC 程序（最后下载到 PLC 的那份）。cell/plant 包按控制单元编号存；factory 包按 PLC 块编号存（一座工厂可以有多台 PLC）
  model.yaml         产线课 / 提交工厂：学生的工厂模型
  answers.json       作答（选择题、图上点选、排故结论）
  runlog.json        本地运行记录摘要（供老师参考，不参与评分）

版本兼容：只用到版本 1 功能的包（PLC 课、产线课、排故课）仍然写成 version 1，老服务器照样能收；factory 包写 version 2。
读包时版本 ≤ VERSION 都认（4.4 服务器读 4.2/4.3 客户端交的版本 1 包），比服务器新的拒收并提示升级。

哈希只用来发现文件损坏，不是防作弊：服务器拿程序 / 模型 / 作答重新评分，和沙箱提交走同一套代码，包里的 local_score 只做参考。

  build(meta, programs, model, answers, runlog) -> bytes
  read(data) -> Package（坏包抛 PackageError，信息是中文）
  artifact(pkg, task) -> 评分用的提交物（cell：程序；plant：模型）
  check_target(pkg, a, task) -> 包和作业对不上时抛 PackageError
"""
from ..i18n import _tr
import base64
import hashlib
import io
import json
import time
import zipfile

import yaml

FORMAT = 'vfhw'
VERSION = 2                      # 能读的最高版本；写包时按内容取最低够用的版本（见 version_for）
KINDS_V1 = ('cell', 'plant', 'diagnose')
MAX_BYTES = 5 * 1024 * 1024
EXT = '.vfhw'
_ALLOWED = ('manifest.json', 'model.yaml', 'answers.json', 'runlog.json', 'mes_snapshot.json')


class PackageError(ValueError):
    pass


def client_version():
    try:
        from .. import __version__
        return str(__version__)
    except Exception:
        return ''


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _json(v):
    return json.dumps(v, ensure_ascii=False, indent=1, default=str).encode('utf-8')


def version_for(meta: dict) -> int:
    """写包用的版本：只用到版本 1 的内容写 1（老服务器能收），提交工厂（kind=factory）写 2。"""
    return 1 if (meta or {}).get('kind', 'cell') in KINDS_V1 and 'plant' not in (meta or {}) else 2


def build(meta: dict, programs: dict | None = None, model: dict | None = None, answers: dict | None = None, runlog: dict | None = None,
          mes_snapshot: dict | None = None) -> bytes:
    """meta：manifest 里除 files/sha256 以外的字段。programs：{单元编号 / PLC 块编号: 程序}。返回 zip 字节。"""
    files = {}
    for bid, p in (programs or {}).items():
        if p:
            files[f'program/{_safe(bid)}.json'] = _json(p)
    if model:
        files['model.yaml'] = yaml.safe_dump(model, allow_unicode=True, sort_keys=False).encode('utf-8')
    if answers:
        files['answers.json'] = _json(answers)
    if runlog:
        files['runlog.json'] = _json(runlog)
    if mes_snapshot is not None:                     # 4.6 MES 课：交作业时本机 MES 的快照 {规则编号: 值}
        files['mes_snapshot.json'] = _json(mes_snapshot)
    man = {'format': FORMAT, 'version': version_for(meta), 'client_version': client_version(), 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
           **(meta or {})}
    man['files'] = sorted(files)
    man['sha256'] = {k: _sha(v) for k, v in files.items()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', _json(man))
        for k, v in files.items():
            z.writestr(k, v)
    out = buf.getvalue()
    if len(out) > MAX_BYTES:
        raise PackageError(_tr('作业包超过 {v} MB', v=MAX_BYTES // 1024 // 1024))
    return out


def _safe(x):
    s = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in str(x))[:64]
    return s or 'cell'


class Package:
    def __init__(self, manifest, programs, model, answers, runlog, raw, mes_snapshot=None):
        self.manifest, self.programs, self.model, self.answers, self.runlog, self.raw = manifest, programs, model, answers, runlog, raw
        self.mes_snapshot = mes_snapshot

    @property
    def kind(self):
        return self.manifest.get('kind') or ('plant' if self.model and not self.programs else 'cell')

    def summary(self):
        m = self.manifest
        return {k: m.get(k) for k in ('format', 'version', 'client_version', 'created', 'student', 'server', 'assignment_id', 'title', 'course', 'lesson',
                                      'scene', 'kind', 'local_score', 'plant')} | {'files': m.get('files') or [], 'size': len(self.raw),
                                                                           'cells': sorted(self.programs), 'has_model': self.model is not None,
                                                                           'answers': len(self.answers or {})}


def decode(body) -> bytes:
    """接口收到的包：原始字节，或 {data: base64 / dataURL}。"""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, dict):
        d = body.get('data') or body.get('package') or ''
        if isinstance(d, str) and d.startswith('data:'):
            d = d.split(',', 1)[-1]
        try:
            return base64.b64decode(d, validate=False)
        except Exception:
            raise PackageError(_tr('作业包数据不是有效的 base64'))
    raise PackageError(_tr('没有收到作业包'))


def read(data: bytes) -> Package:
    if not data:
        raise PackageError(_tr('作业包是空的'))
    if len(data) > MAX_BYTES:
        raise PackageError(_tr('作业包超过 {v} MB', v=MAX_BYTES // 1024 // 1024))
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError(_tr('不是作业包（.vfhw）文件，或者文件已损坏'))
    with z:
        names = z.namelist()
        total = sum(i.file_size for i in z.infolist())
        if total > MAX_BYTES * 4:
            raise PackageError(_tr('作业包解压后太大'))
        if 'manifest.json' not in names:
            raise PackageError(_tr('作业包里没有 manifest.json'))
        try:
            man = json.loads(z.read('manifest.json').decode('utf-8'))
        except ValueError:
            raise PackageError(_tr('manifest.json 不是有效的 JSON'))
        if not isinstance(man, dict) or man.get('format') != FORMAT:
            raise PackageError(_tr('不是作业包（manifest.format 不是 vfhw）'))
        try:
            ver = int(man.get('version') or 0)
        except (TypeError, ValueError):
            raise PackageError(_tr('manifest 里的版本号不对'))
        if ver > VERSION:
            raise PackageError(_tr('作业包版本 {get} 比服务器新，请升级服务器', get=man.get('version')))
        sha = man.get('sha256') or {}
        programs, model, answers, runlog, snap = {}, None, {}, None, None
        for n in names:
            if n == 'manifest.json' or n.endswith('/'):
                continue
            if not (n in _ALLOWED or (n.startswith('program/') and n.endswith('.json') and n.count('/') == 1)):
                raise PackageError(_tr('作业包里有不认识的文件：{n}', n=n))
            b = z.read(n)
            if n not in sha:
                raise PackageError(_tr('manifest 里没有 {n} 的校验值', n=n))
            if _sha(b) != sha[n]:
                raise PackageError(_tr('{n} 校验不对：文件可能损坏了，请重新导出', n=n))
            try:
                if n == 'model.yaml':
                    model = yaml.safe_load(b.decode('utf-8'))
                    if not isinstance(model, dict):
                        raise PackageError(_tr('model.yaml 不是工厂模型'))
                elif n == 'answers.json':
                    answers = json.loads(b.decode('utf-8')) or {}
                elif n == 'runlog.json':
                    runlog = json.loads(b.decode('utf-8'))
                elif n == 'mes_snapshot.json':
                    snap = json.loads(b.decode('utf-8'))
                    if not isinstance(snap, dict):
                        raise PackageError(_tr('mes_snapshot.json 应该是 {规则编号: 值}'))
                else:
                    programs[n[len('program/'):-5]] = json.loads(b.decode('utf-8'))
            except (ValueError, yaml.YAMLError):
                raise PackageError(_tr('{n} 内容格式不对', n=n))
        for n in sha:
            if n not in names:
                raise PackageError(_tr('作业包缺文件：{n}', n=n))
    if not isinstance(answers, dict):
        raise PackageError(_tr('answers.json 应该是 {题号: 答案}'))
    if man.get('kind') == 'factory':
        if ver < 2:
            raise PackageError(_tr('提交工厂的作业包至少是版本 2'))
        if model is None:
            raise PackageError(_tr('提交工厂的作业包里没有工厂模型（model.yaml）'))
    return Package(man, programs, model, answers, runlog, data, snap)


def check_target(pkg: Package, a: dict, task) -> None:
    """包是不是这个作业的：有作业号时必须一致；没有时按课程/课或场景对。"""
    m = pkg.manifest
    aid = m.get('assignment_id')
    if aid not in (None, ''):
        try:
            n = int(aid)
        except (TypeError, ValueError):
            raise PackageError(_tr('manifest 里的作业号不对'))
        if n != int(a['id']):
            raise PackageError(_tr('这个作业包是作业 {aid} 的，不是这个作业（{id}）', aid=aid, id=a['id']))
    if a.get('course') and m.get('course') and (m.get('course'), m.get('lesson')) != (a['course'], a['lesson']):
        raise PackageError(_tr('这个作业包是课程 {get}/{get2} 的，不是这一课', get=m.get('course'), get2=m.get('lesson')))
    if not a.get('course') and m.get('scene') and a.get('scene') and m['scene'] != a['scene']:
        raise PackageError(_tr('这个作业包是场景 {scene} 的，不是这个任务（{scene2}）', scene=m['scene'], scene2=a['scene']))
    if m.get('kind') and m['kind'] != task.kind:
        raise PackageError(_tr('作业包类型是 {kind}，这个任务是 {kind2}', kind=m['kind'], kind2=task.kind))


def artifact(pkg: Package, task):
    """评分用的提交物。cell：场景控制单元的程序（只有一个单元时取那个）；plant/diagnose：模型；factory：{model, programs}（模型 + 每台 PLC 的程序）。"""
    if task.kind == 'factory':
        if not pkg.model or not isinstance(pkg.model.get('blocks'), list):
            raise PackageError(_tr('作业包里没有工厂模型（model.yaml），或者不是 2.0 以后的工厂模型'))
        return {'model': pkg.model, 'programs': {k: v for k, v in pkg.programs.items() if isinstance(v, dict) and v.get('source')}}
    if task.kind == 'cell':
        if not pkg.programs:
            raise PackageError(_tr('作业包里没有 PLC 程序'))
        want = None
        try:
            from . import scenes
            want = (scenes.cell_of(task.scene) or {}).get('id')
        except Exception:
            want = None
        p = pkg.programs.get(_safe(want)) if want else None
        if p is None:
            p = pkg.programs.get('CELL1') or next(iter(pkg.programs.values()))
        if not isinstance(p, dict) or not p.get('source'):
            raise PackageError(_tr('作业包里的 PLC 程序是空的'))
        return p
    if task.kind in ('quiz', 'mes'):                 # 4.6 测验 / MES 课：只有作答（answers.json）；MES 课另有交作业时的 MES 快照
        return {'kind': task.kind, 'mes_snapshot': pkg.mes_snapshot} if task.kind == 'mes' else {'kind': task.kind}
    if not pkg.model:
        raise PackageError(_tr('作业包里没有产线模型（model.yaml）'))
    return pkg.model


def filename(meta: dict) -> str:
    who = (meta.get('student') or {}).get('username') or 'local'
    what = meta.get('lesson') or meta.get('scene') or (meta.get('plant') or {}).get('id') or 'task'
    return f"{_safe(who)}-{_safe(what)}-{time.strftime('%m%d%H%M')}{EXT}"
