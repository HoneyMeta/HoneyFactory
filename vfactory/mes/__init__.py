"""本机 MES（蜂元教学 MES）：客户端按需启动的第二个本地服务（4.6）。

- sidecar.py      启动/停止/状态/空闲自动停止、客户端接口 /api/desktop/mes/*、页面取数的转发 /api/mes/*（只在桌面模式注册，服务器上没有）
- teach_rules.py  MES 课（kind=mes）的评分取数：给 courses/rules.register_mes 挂取数函数（评分进程池里由 load_mes_providers 导入）

蜂元教学 MES 的代码就在本仓库：vfmes/（Python 包，python -m vfmes serve，只有接口），页面在虚拟工厂的网页里（web/src/mes/，5.0.1），说明见 vfmes/README.md。
安装包里它们和 vfactory 一起在 resources\\vf 下（tools\\build_electron.ps1）。和智能 MOM（HoneyMOM）是两个产品，不依赖那个仓库。
"""
