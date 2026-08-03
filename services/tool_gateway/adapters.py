"""工具执行层：确认后的深链生成 + 域名白名单。

红线（文档 05/15 节）：
- 任何外部动作必须发生在 human_confirmed 之后（调用方负责校验）
- 只生成白名单域名的深链；不做真实支付、不自动下单
- 深链交给手机/Web 端打开，执行结果回写 ActionResult 并落 Ledger
"""
from __future__ import annotations

from urllib.parse import quote

from core.decision_schema import ActionResult, Candidate, Channel

# 白名单：深链只允许这些域名/scheme。NemoClaw/OpenShell 接入后由其实时审批替代静态表。
ALLOWED_DOMAINS = {
    "uri.amap.com",       # 高德地图 H5/URI API
    "www.meituan.com",    # 美团搜索页
    "h5.ele.me",          # 饿了么 H5
}


def build_action(candidate: Candidate, channel: Channel,
                 budget_max: float | None = None) -> ActionResult:
    """按渠道生成执行深链。dine_in → 地图导航；delivery → 外卖平台搜索页。

    app_url：淘宝 App 的 tbopen scheme，把闪购 H5 包进 App 内打开——
    用 App 里已登录的会话，绕开网页端登录墙；打不开（未装 App）由前端回落 url。
    """
    app_url = ""
    if channel == Channel.dine_in or (
        channel == Channel.any and candidate.channel == Channel.dine_in
    ):
        url = (f"https://uri.amap.com/search?keyword={quote(candidate.restaurant)}"
               f"&view=map&src=noon-decision-os")
        action = "map_deeplink"
    else:
        # 搜菜名不搜店名：演示餐厅是合成数据，真实平台搜不到；菜名是通用词，
        # 附近真实商家都能命中——"这道菜附近谁家有"才是可下单的落点
        import re
        dish = re.sub(r"(小份|大份|中份|微辣|中辣|特辣|单人餐|双人份|双人套餐|套餐)+$",
                      "", candidate.item).strip() or candidate.item
        url = f"https://h5.ele.me/search/?keyword={quote(dish)}"
        action = "order_deeplink"
        # 淘宝原生搜索 scheme：直落带关键词的结果页（闪购/秒送在结果内）。
        # 此前 tbopen 包 H5 的方案实测关键词会被 SPA 吞掉，落到空搜索页。
        app_url = f"taobao://s.taobao.com/search?q={quote(dish)}"
        if budget_max:
            # 用户口述预算 → 价格区间筛选（老参数，部分版本可能忽略；忽略则等同纯搜索）
            app_url += quote(f"&filter=reserve_price[,{int(budget_max)}]", safe="&=")
    domain = url.split("/")[2]
    if domain not in ALLOWED_DOMAINS:
        return ActionResult(action=action, url="", approved_by_user=True,
                            ok=False, error=f"domain {domain} not in whitelist")
    return ActionResult(action=action, url=url, app_url=app_url,
                        approved_by_user=True, ok=True)
