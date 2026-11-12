"""服务器复评 / 防作弊的挂钩（5.0 不做，只留接口）。

SaaS 服务器不跑仿真：学生交的作业包按客户端本机评的分记（来源 client，details 里 verified=false）。以后要做服务器复评（另起评分机，
或抽查）时，在这里注册一个函数，签名 fn(submission_row: dict, package) -> dict | None：
  返回 None：不处理（保持客户端分数）；返回 {'score': 0~100, 'details': [...], 'verified': True}：用复评结果覆盖。
复评可以很慢——调用方在后台任务里调，不阻塞交作业。
"""
from ..i18n import _tr
import logging

log = logging.getLogger('vfactory.tenancy')
_rescorers: list = []


def register_rescorer(fn):
    _rescorers.append(fn)


def rescore(row, pkg):
    """依次问注册的复评函数，第一个给出结果的算数。没有注册任何函数时返回 None（5.0 的情况）。"""
    for fn in list(_rescorers):
        try:
            r = fn(row, pkg)
        except Exception:                      # noqa: BLE001  复评出错不影响已记下的提交
            log.exception(_tr('复评出错'))
            continue
        if r:
            return r
    return None
