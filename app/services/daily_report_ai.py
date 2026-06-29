import json
from datetime import datetime
from urllib import error, request

from app.services.llm_settings import get_effective_llm_settings
from app.config import LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS


TOP_SECTION_FIELDS = ("business_stability", "trend_comparison", "overall_assessment")

FIELD_INSTRUCTIONS = {
    "business_stability": "业务运行情况：只写1句话，优先贴近历史成稿句式‘今日业务运行稳定，……，整体安全状态稳定。’；先写运行状态，再写是否存在主机入侵或核心异常，结尾落到‘整体安全状态稳定/平稳’，不要写趋势判断，不要出现‘总体来看’。",
    "trend_comparison": "趋势对比说明：只写1句话，必须使用‘与昨日相比，’起句；只比较WAF、CFW、HSS、SecMaster等核心指标的上升、下降或持平，避免逐项罗列具体增减值，优先归纳为‘有所上升/有所下降/基本持平’；对同向且波动幅度接近的指标优先合并表述，如‘WAF攻击数量、HSS告警数量均有所下降’；可在句末补‘整体波动处于预期范围内’，无昨日数据时写‘与昨日相比，因缺少基线数据，暂无法开展趋势对比。’。",
    "overall_assessment": "总体评估：只写1句话，必须使用‘总体来看，’起句；优先贴近历史成稿句式‘总体来看，整体安全态势保持平稳可控。’；只给结论，不重复罗列产品数据，不写建议项。",
}

STYLE_EXAMPLES = {
    "business_stability": "今日业务运行稳定，无主机入侵事件，整体安全状态稳定。",
    "trend_comparison": "与昨日相比，WAF攻击数量、HSS告警数量均有所下降，SecMaster告警数量有所上升，CFW攻击数量基本持平，整体波动处于预期范围内。",
    "overall_assessment": "总体来看，整体安全态势保持平稳可控。",
}


def generate_top_section_text(
    report: dict[str, object],
    previous: dict[str, object] | None = None,
    fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, str]:
    target_fields = _normalize_fields(fields)
    fallback = _generate_fallback_text(report, previous, target_fields)
    # 兼容：测试或旧代码可能直接 patch 模块级常量，优先使用这些常量构造临时设置
    if LLM_API_BASE_URL or LLM_API_KEY or LLM_MODEL:
        llm_settings = {
            "enabled": bool(LLM_API_BASE_URL and LLM_API_KEY and LLM_MODEL),
            "api_base_url": LLM_API_BASE_URL or "",
            "api_key": LLM_API_KEY or "",
            "model": LLM_MODEL or "",
            "timeout_seconds": int(LLM_TIMEOUT_SECONDS or 30),
            "source": "module",
        }
    else:
        llm_settings = get_effective_llm_settings()
    if not (
        bool(llm_settings.get("enabled"))
        and str(llm_settings.get("api_base_url", "")).strip()
        and str(llm_settings.get("api_key", "")).strip()
        and str(llm_settings.get("model", "")).strip()
    ):
        return fallback

    try:
        llm_result = _call_llm(report, previous, target_fields, llm_settings)
    except Exception:
        return fallback

    return {
        field: str(llm_result.get(field) or fallback[field]).strip()
        for field in target_fields
    }


def _call_llm(
    report: dict[str, object],
    previous: dict[str, object] | None,
    fields: tuple[str, ...],
    llm_settings: dict[str, object],
) -> dict[str, str]:
    prompt = _build_prompt(report, previous, fields)
    payload = {
        "model": llm_settings["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业安全运营日报写作助手。"
                    "请严格模仿企业安全运营日报的历史成稿口径，句式克制、偏书面、偏结论化，不写营销语言，不写套话，不写 Markdown。"
                    "顶部三段要写成可直接贴入正式日报模板的成稿，不要写成模型说明或数据摘要。"
                    "其中业务运行情况优先贴近‘今日业务运行稳定，……，整体安全状态稳定。’；"
                    "趋势对比说明优先贴近‘与昨日相比，……，整体波动处于预期范围内。’；"
                    "趋势对比说明不要逐项堆砌具体增减值，优先合并同向且幅度接近的指标；"
                    "总体评估优先贴近‘总体来看，整体安全态势保持平稳可控。’。"
                    f"请仅输出 JSON，对象中必须只包含这几个字段：{', '.join(fields)}。"
                    "不得输出字段说明、标题、前后缀。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        url=f"{llm_settings['api_base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_settings['api_key']}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=int(llm_settings.get("timeout_seconds", 30) or 30)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError("LLM request failed") from exc

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = json.loads(content)
    return {field: str(parsed.get(field, "")).strip() for field in fields}


def _build_prompt(report: dict[str, object], previous: dict[str, object] | None, fields: tuple[str, ...]) -> str:
    lines = [
        "请根据以下安全日报数据，生成指定字段的文本。",
        "统一要求：",
        "1. 每个字段只输出1句话。",
        "2. 语言风格要贴近日报成稿：正式、简洁、稳健、少修饰，像人工整理后的正式日报。",
        "3. 优先沿用历史句式骨架：‘今日业务运行稳定’、‘与昨日相比’、‘总体来看’。",
        "4. 不要编造未提供的数据，不要重复堆砌原始数字，不要写建议、研判过程或口语化衔接。",
        "5. 若字段没有足够依据，只能做保守表述。",
        "本次需要生成的字段与要求：",
    ]
    lines.extend(f"- {field}: {FIELD_INSTRUCTIONS[field]} 示例：{STYLE_EXAMPLES[field]}" for field in fields)
    lines.extend([
        "当前数据：",
        json.dumps(_prompt_report_snapshot(report), ensure_ascii=False),
    ])
    if previous:
        lines.extend(["昨日数据：", json.dumps(_prompt_report_snapshot(previous), ensure_ascii=False)])
    return "\n".join(lines)



def _normalize_fields(fields: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not fields:
        return TOP_SECTION_FIELDS
    normalized = tuple(field for field in fields if field in TOP_SECTION_FIELDS)
    return normalized or TOP_SECTION_FIELDS

def _prompt_report_snapshot(report: dict[str, object]) -> dict[str, object]:
    return {
        "report_date": report.get("report_date", ""),
        "monitor_start": report.get("monitor_start", ""),
        "monitor_end": report.get("monitor_end", ""),
        "waf_attacks": int(report.get("waf_attacks", 0) or 0),
        "waf_blocked": int(report.get("waf_blocked", 0) or 0),
        "waf_ips_banned": int(report.get("waf_ips_banned", 0) or 0),
        "cfw_attacks": int(report.get("cfw_attacks", 0) or 0),
        "cfw_unblocked": int(report.get("cfw_unblocked", 0) or 0),
        "hss_alerts": int(report.get("hss_alerts", 0) or 0),
        "hss_unclosed_event_count": int(report.get("hss_unclosed_event_count", 0) or 0),
        "ddos_cleanings": int(report.get("ddos_cleanings", 0) or 0),
        "ddos_blackholes": int(report.get("ddos_blackholes", 0) or 0),
        "secmaster_alerts": int(report.get("secmaster_alerts", 0) or 0),
        "secmaster_unclosed_event_count": int(report.get("secmaster_unclosed_event_count", 0) or 0),
    }


def _generate_fallback_text(report: dict[str, object], previous: dict[str, object] | None, fields: tuple[str, ...]) -> dict[str, str]:
    total_alerts = sum(
        int(report.get(field, 0) or 0)
        for field in ("waf_blocked", "hss_alerts", "secmaster_alerts")
    )
    total_attacks = int(report.get("waf_attacks", 0) or 0) + int(report.get("cfw_attacks", 0) or 0)
    unclosed = int(report.get("hss_unclosed_event_count", 0) or 0) + int(report.get("secmaster_unclosed_event_count", 0) or 0)
    blackholes = int(report.get("ddos_blackholes", 0) or 0)

    if total_attacks == 0 and total_alerts == 0 and blackholes == 0 and unclosed == 0:
        business = "今日业务运行稳定，未发现主机入侵事件，整体安全状态稳定。"
    elif unclosed == 0 and blackholes == 0:
        business = (
            f"今日业务运行稳定，WAF与CFW累计发现攻击{total_attacks}次，"
            f"HSS与SecMaster累计产生告警{total_alerts}次，整体安全状态稳定。"
        )
    else:
        business = (
            f"今日业务运行稳定，WAF与CFW累计发现攻击{total_attacks}次，"
            f"HSS与SecMaster累计产生告警{total_alerts}次，当前仍有{unclosed}起事件待持续跟进。"
        )

    trend = _build_trend_text(report, previous)

    if blackholes > 0 or unclosed > 0:
        overall = "总体来看，整体安全态势总体可控，但仍需持续跟进未闭环事件与重点告警处置情况。"
    elif total_attacks or total_alerts:
        overall = "总体来看，整体安全态势保持平稳可控，现网攻击与告警波动均处于可监测、可处置范围内。"
    else:
        overall = "总体来看，整体安全态势保持平稳，未见对业务造成明显影响的安全风险。"

    source = {
        "business_stability": business,
        "trend_comparison": trend,
        "overall_assessment": overall,
    }
    return {field: source[field] for field in fields}


def _build_trend_text(report: dict[str, object], previous: dict[str, object] | None) -> str:
    if not previous:
        return "与昨日相比，因缺少基线数据，暂无法开展趋势对比。"

    items = [
        _build_trend_item("WAF攻击数量", report, previous, "waf_attacks"),
        _build_trend_item("CFW攻击数量", report, previous, "cfw_attacks"),
        _build_trend_item("HSS告警数量", report, previous, "hss_alerts"),
        _build_trend_item("SecMaster告警数量", report, previous, "secmaster_alerts"),
    ]
    if all(item["direction"] == "flat" for item in items):
        return "与昨日相比，各项核心攻击与告警指标整体持平，暂无明显波动。"
    phrases: list[str] = []
    for direction in ("down", "up", "flat"):
        direction_items = [item for item in items if item["direction"] == direction]
        phrases.extend(_render_trend_group(group) for group in _group_trend_items(direction_items))
    return f"与昨日相比，{'，'.join(phrases)}，整体波动处于预期范围内。"


def _build_trend_item(
    label: str,
    report: dict[str, object],
    previous: dict[str, object],
    field: str,
) -> dict[str, object]:
    current = int(report.get(field, 0) or 0)
    last = int(previous.get(field, 0) or 0)
    delta = current - last
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"

    percent = None
    if last > 0:
        percent = abs(delta) / last

    return {
        "label": label,
        "direction": direction,
        "percent": percent,
    }


def _group_trend_items(items: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    if not items:
        return []
    if items[0]["direction"] == "flat":
        return [items]

    groups: list[list[dict[str, object]]] = []
    for item in items:
        matched_group = next(
            (group for group in groups if _trend_magnitude_close(group, item)),
            None,
        )
        if matched_group is None:
            groups.append([item])
        else:
            matched_group.append(item)
    return groups


def _trend_magnitude_close(group: list[dict[str, object]], item: dict[str, object]) -> bool:
    group_percents = [value for value in (member["percent"] for member in group) if value is not None]
    item_percent = item["percent"]
    if not group_percents or item_percent is None:
        return False
    average = sum(group_percents) / len(group_percents)
    return abs(average - item_percent) <= 0.15


def _render_trend_group(group: list[dict[str, object]]) -> str:
    labels = "、".join(str(item["label"]) for item in group)
    direction = str(group[0]["direction"])
    if direction == "flat":
        return f"{labels}基本持平"
    if direction == "up":
        return f"{labels}{'均' if len(group) > 1 else ''}有所上升"
    return f"{labels}{'均' if len(group) > 1 else ''}有所下降"


def _monitor_window(report: dict[str, object]) -> str:
    start = str(report.get("monitor_start", "")).strip()
    end = str(report.get("monitor_end", "")).strip()
    if not start or not end:
        return ""
    return f"监控时间{_format_monitor(start)}至{_format_monitor(end)}期间，"


def _format_monitor(raw: str) -> str:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            value = datetime.strptime(raw, fmt)
            return f"{value.year}年{value.month}月{value.day}日 {value:%H:%M}"
        except ValueError:
            continue
    return raw
