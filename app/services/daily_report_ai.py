import json
from datetime import datetime
from urllib import error, request

from app.services.llm_settings import get_effective_llm_settings
from app.config import LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS


TOP_SECTION_FIELDS = ("business_stability", "trend_comparison", "overall_assessment")

FLUCTUATION_METRICS = (
    ("waf", "WAF 应用防火墙", "攻击数量", "waf_attacks"),
    ("cfw", "CFW 云防火墙", "攻击数量", "cfw_attacks"),
    ("hss", "HSS 主机安全", "告警数量", "hss_alerts"),
    ("secmaster", "SecMaster 态势感知", "告警数量", "secmaster_alerts"),
)

FLUCTUATION_KEY_LABELS = {
    "waf": "WAF",
    "cfw": "CFW",
    "hss": "HSS",
    "secmaster": "SecMaster",
}

FIELD_INSTRUCTIONS = {
    "business_stability": "业务运行情况：只写1句话，优先贴近历史成稿句式‘今日业务运行稳定，……，整体安全状态稳定。’；先写运行状态，再写是否存在主机入侵或核心异常，结尾落到‘整体安全状态稳定/平稳’，不要写趋势判断，不要出现‘总体来看’。",
    "trend_comparison": "趋势对比说明：只写1句话，必须使用‘与昨日相比，’起句；比较WAF、CFW、HSS、SecMaster等核心指标的上升、下降或持平，避免逐项罗列具体增减值，对同向且波动幅度接近的指标优先合并表述；人工未补充波动原因时，不分析或推测原因，统一以‘各设备的攻击及告警数量波动均处于正常范围’结尾，不得写‘原因暂无法确认’或‘进一步核实’；无昨日数据时写‘与昨日相比，因缺少基线数据，暂无法开展趋势对比。’。",
    "overall_assessment": "总体评估：只写1句话，必须使用‘总体来看，’起句；优先贴近历史成稿句式‘总体来看，整体安全态势保持平稳可控。’；只给结论，不重复罗列产品数据，不写建议项。",
}

STYLE_EXAMPLES = {
    "business_stability": "今日业务运行稳定，无主机入侵事件，整体安全状态稳定。",
    "trend_comparison": "与昨日相比，WAF攻击数量、HSS告警数量均有所下降，SecMaster告警数量有所上升，CFW攻击数量基本持平；各设备的攻击及告警数量波动均处于正常范围。",
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

    result = {
        field: str(llm_result.get(field) or fallback[field]).strip()
        for field in target_fields
    }
    if "trend_comparison" in result:
        result["trend_comparison"] = _apply_comparison_reference(
            result["trend_comparison"], report, previous
        )
        result["trend_comparison"] = _ensure_trend_reason_analysis(
            result["trend_comparison"], report, previous
        )
    return result


def detect_large_fluctuations(
    report: dict[str, object],
    previous: dict[str, object] | None,
    threshold: float = 0.5,
) -> list[dict[str, object]]:
    """Return devices whose attack or alert count changed beyond the threshold."""
    if not previous:
        return []

    fluctuations: list[dict[str, object]] = []
    previous_date = str(previous.get("report_date", "") or "").strip()
    for key, name, metric, field in FLUCTUATION_METRICS:
        current = _safe_count(report.get(field, 0))
        baseline = _safe_count(previous.get(field, 0))
        delta = current - baseline
        if delta == 0:
            continue

        percent: float | None = None
        if baseline > 0:
            ratio = abs(delta) / baseline
            if ratio < threshold:
                continue
            percent = round(ratio * 100, 1)
        elif current <= 0:
            continue

        fluctuations.append(
            {
                "key": key,
                "name": name,
                "metric": metric,
                "current": current,
                "previous": baseline,
                "previous_date": previous_date,
                "delta": delta,
                "percent": percent,
                "direction": "up" if delta > 0 else "down",
            }
        )
    return fluctuations


def _safe_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def polish_trend_comparison_with_reasons(
    trend_comparison: str,
    reason_groups: list[dict[str, object]],
    fluctuations: list[dict[str, object]] | None = None,
) -> str:
    """Polish the generated trend paragraph with user-confirmed fluctuation reasons."""
    normalized_groups = _normalize_fluctuation_reason_groups(reason_groups)
    normalized_fluctuations = _normalize_trend_fluctuations(fluctuations or [])
    source_text = str(trend_comparison or "").strip()
    if not normalized_groups:
        return source_text

    fallback = _build_reason_polish_fallback(
        source_text,
        normalized_groups,
        normalized_fluctuations,
    )
    if LLM_API_BASE_URL or LLM_API_KEY or LLM_MODEL:
        llm_settings = {
            "enabled": bool(LLM_API_BASE_URL and LLM_API_KEY and LLM_MODEL),
            "api_base_url": LLM_API_BASE_URL or "",
            "api_key": LLM_API_KEY or "",
            "model": LLM_MODEL or "",
            "timeout_seconds": int(LLM_TIMEOUT_SECONDS or 30),
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
        polished = _call_trend_reason_polish_llm(
            source_text,
            normalized_groups,
            normalized_fluctuations,
            llm_settings,
        )
    except Exception:
        return fallback
    if polished and _polished_text_covers_fluctuations(polished, normalized_fluctuations):
        return polished
    return fallback


def _normalize_fluctuation_reason_groups(
    reason_groups: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped_metrics: dict[str, list[str]] = {}
    for group in reason_groups or []:
        if not isinstance(group, dict):
            continue
        reason = str(group.get("reason", "") or "").strip().rstrip("。；;，, ")
        raw_metrics = group.get("device_metrics", [])
        if not reason or not isinstance(raw_metrics, list):
            continue
        metrics = [str(metric).strip() for metric in raw_metrics if str(metric).strip()]
        if not metrics:
            continue
        target = grouped_metrics.setdefault(reason, [])
        for metric in metrics:
            if metric not in target:
                target.append(metric)
    return [
        {"reason": reason, "device_metrics": metrics}
        for reason, metrics in grouped_metrics.items()
    ]


def _normalize_trend_fluctuations(
    fluctuations: list[dict[str, object]],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in fluctuations:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "") or "").strip().lower()
        direction = str(item.get("direction", "") or "").strip().lower()
        metric = str(item.get("metric", "") or "").strip()
        name = str(item.get("name", "") or "").strip()
        if key not in FLUCTUATION_KEY_LABELS or direction not in {"up", "down"} or not metric:
            continue
        normalized.append(
            {
                "key": key,
                "label": f"{FLUCTUATION_KEY_LABELS[key]}{metric}",
                "device_metric": f"{name}{metric}" if name else f"{FLUCTUATION_KEY_LABELS[key]}{metric}",
                "direction": direction,
                "direction_text": "上升" if direction == "up" else "下降",
            }
        )
    return normalized


def _build_reason_polish_fallback(
    trend_comparison: str,
    reason_groups: list[dict[str, object]],
    fluctuations: list[dict[str, str]],
) -> str:
    details: list[str] = []
    confirmed_metrics: set[str] = set()
    for group in reason_groups:
        metrics = "、".join(str(metric) for metric in group["device_metrics"])
        confirmed_metrics.update(str(metric) for metric in group["device_metrics"])
        reason = str(group["reason"])
        qualifier = "均是" if len(group["device_metrics"]) > 1 else "是"
        details.append(f"本次{metrics}异常{qualifier}受{reason}影响")
    has_unconfirmed = any(
        item["device_metric"] not in confirmed_metrics
        for item in fluctuations
    )
    if has_unconfirmed:
        details.append("其余设备的攻击及告警数量波动均处于正常范围")
    source = trend_comparison.strip().rstrip("。；; ")
    verified = "；".join(details) + "。"
    return f"{source}；{verified}" if source else verified


def _polished_text_covers_fluctuations(
    text: str,
    fluctuations: list[dict[str, str]],
) -> bool:
    lowered = text.lower()
    return all(FLUCTUATION_KEY_LABELS[item["key"]].lower() in lowered for item in fluctuations)


def _call_trend_reason_polish_llm(
    trend_comparison: str,
    reason_groups: list[dict[str, object]],
    fluctuations: list[dict[str, str]],
    llm_settings: dict[str, object],
) -> str:
    payload = {
        "model": llm_settings["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业安全运营日报编辑。请将原趋势文案与运营人员核实的真实原因整合为一段正式成稿。"
                    "必须保留原文中的指标变化事实，不得改变上升、下降或持平结论；用户填写的原因属于已核实事实，"
                    "应替换对应设备原文中笼统的推测性原因。输出必须覆盖波动清单中的每个设备及其变化方向，"
                    "不得因为运营人员只填写了某个设备的原因而省略其他设备。未填写原因表示该设备变化处于正常范围，"
                    "保留其变化方向后统一表述为‘其余设备的攻击及告警数量波动均处于正常范围’，不要写原因仍需核实。"
                    "相同原因对应多个设备时必须合并表达，"
                    "使用‘本次……异常均是受……影响’句式。文字应简洁、连贯、书面化，不得编造新原因，不输出 Markdown。"
                    "请仅输出 JSON，格式为 {\"trend_comparison\": \"润色后的完整文案\"}。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"原趋势文案：{trend_comparison}\n"
                    "全部波动设备及方向："
                    f"{json.dumps(fluctuations, ensure_ascii=False)}\n"
                    "已核实的波动原因："
                    f"{json.dumps(reason_groups, ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.1,
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
        raise RuntimeError("LLM trend polish request failed") from exc

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = json.loads(content)
    return str(parsed.get("trend_comparison", "") or "").strip()


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
                    "趋势对比说明只写清指标变化；人工未补充波动原因时，不分析或推测原因，"
                    "统一以‘各设备的攻击及告警数量波动均处于正常范围’结尾，"
                    "不得写‘初步判断’‘可能与’‘原因暂无法确认’或‘进一步核实’；"
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
    comparison_reference = _comparison_reference(report, previous)
    lines = [
        "请根据以下安全日报数据，生成指定字段的文本。",
        "统一要求：",
        "1. 每个字段只输出1句话。",
        "2. 语言风格要贴近日报成稿：正式、简洁、稳健、少修饰，像人工整理后的正式日报。",
        f"3. 优先沿用历史句式骨架：‘今日业务运行稳定’、‘{comparison_reference}’、‘总体来看’。",
        "4. 不要编造未提供的数据，不要重复堆砌原始数字，不要写建议、研判过程或口语化衔接。",
        "5. 趋势对比只描述指标变化；人工未补充原因时，不分析或推测变化原因。",
        "6. 趋势对比统一以‘各设备的攻击及告警数量波动均处于正常范围’结尾，不得写‘原因暂无法确认’或‘进一步核实’。",
        "本次需要生成的字段与要求：",
    ]
    lines.extend(
        f"- {field}: {FIELD_INSTRUCTIONS[field].replace('与昨日相比', comparison_reference).replace('无昨日数据', '无基准数据' if comparison_reference != '与昨日相比' else '无昨日数据')} "
        f"示例：{STYLE_EXAMPLES[field].replace('与昨日相比', comparison_reference)}"
        for field in fields
    )
    lines.extend([
        "当前数据：",
        json.dumps(_prompt_report_snapshot(report), ensure_ascii=False),
    ])
    if previous:
        lines.extend([
            f"对比基准数据（{comparison_reference}）：",
            json.dumps(_prompt_report_snapshot(previous), ensure_ascii=False),
        ])
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
        "waf_qps_peak_value": int(report.get("waf_qps_peak_value", 0) or 0),
        "waf_exceeded_spec": bool(report.get("waf_exceeded_spec", False)),
        "cfw_attacks": int(report.get("cfw_attacks", 0) or 0),
        "cfw_unblocked": int(report.get("cfw_unblocked", 0) or 0),
        "cfw_inbound_peak": str(report.get("cfw_inbound_peak", "") or ""),
        "cfw_inbound_95th": str(report.get("cfw_inbound_95th", "") or ""),
        "cfw_exceeded_spec": bool(report.get("cfw_exceeded_spec", False)),
        "hss_alerts": int(report.get("hss_alerts", 0) or 0),
        "hss_detail_fatal": int(report.get("hss_detail_fatal", 0) or 0),
        "hss_detail_high": int(report.get("hss_detail_high", 0) or 0),
        "hss_detail_medium": int(report.get("hss_detail_medium", 0) or 0),
        "hss_detail_low": int(report.get("hss_detail_low", 0) or 0),
        "hss_unclosed_event_count": int(report.get("hss_unclosed_event_count", 0) or 0),
        "hss_closed_loop_status": str(report.get("hss_closed_loop_status", "") or ""),
        "ddos_cleanings": int(report.get("ddos_cleanings", 0) or 0),
        "ddos_blackholes": int(report.get("ddos_blackholes", 0) or 0),
        "secmaster_alerts": int(report.get("secmaster_alerts", 0) or 0),
        "secmaster_detail_fatal": int(report.get("secmaster_detail_fatal", 0) or 0),
        "secmaster_detail_high": int(report.get("secmaster_detail_high", 0) or 0),
        "secmaster_detail_medium": int(report.get("secmaster_detail_medium", 0) or 0),
        "secmaster_detail_low": int(report.get("secmaster_detail_low", 0) or 0),
        "secmaster_detail_info": int(report.get("secmaster_detail_info", 0) or 0),
        "secmaster_unclosed_event_count": int(report.get("secmaster_unclosed_event_count", 0) or 0),
        "emergency_response": str(report.get("emergency_response", "") or ""),
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
    comparison_reference = _comparison_reference(report, previous)
    if not previous:
        return f"{comparison_reference}，因缺少基线数据，暂无法开展趋势对比。"

    items = [
        _build_trend_item("WAF攻击数量", report, previous, "waf_attacks"),
        _build_trend_item("CFW攻击数量", report, previous, "cfw_attacks"),
        _build_trend_item("HSS告警数量", report, previous, "hss_alerts"),
        _build_trend_item("SecMaster告警数量", report, previous, "secmaster_alerts"),
    ]
    if all(item["direction"] == "flat" for item in items):
        reason = _build_trend_reason_text(report, previous)
        return f"{comparison_reference}，各项核心攻击与告警指标整体持平，暂无明显波动；{reason}。"
    phrases: list[str] = []
    for direction in ("down", "up", "flat"):
        direction_items = [item for item in items if item["direction"] == direction]
        phrases.extend(_render_trend_group(group) for group in _group_trend_items(direction_items))
    reason = _build_trend_reason_text(report, previous)
    return f"{comparison_reference}，{'，'.join(phrases)}；{reason}。"


def _build_trend_reason_text(
    report: dict[str, object],
    previous: dict[str, object],
) -> str:
    return "各设备的攻击及告警数量波动均处于正常范围"


def _ensure_trend_reason_analysis(
    text: str,
    report: dict[str, object],
    previous: dict[str, object] | None,
) -> str:
    if not previous:
        return text
    normalized = text.strip().rstrip("。；; ")
    for marker in ("；", ";", "，结合", "，初步判断", "，可能与", "，具体原因"):
        if marker in normalized:
            normalized = normalized.split(marker, 1)[0].rstrip("，。；; ")
            break
    if not normalized:
        return _build_trend_text(report, previous)
    return f"{normalized}；{_build_trend_reason_text(report, previous)}。"


def _comparison_reference(
    report: dict[str, object], previous: dict[str, object] | None
) -> str:
    if not previous:
        return "与昨日相比"

    try:
        current_date = datetime.strptime(str(report.get("report_date", "")), "%Y-%m-%d").date()
        previous_date = datetime.strptime(str(previous.get("report_date", "")), "%Y-%m-%d").date()
    except ValueError:
        return "与昨日相比"

    if previous_date >= current_date or (current_date - previous_date).days == 1:
        return "与昨日相比"
    if previous_date.year == current_date.year:
        return f"与{previous_date.month}月{previous_date.day}日相比"
    return f"与{previous_date.year}年{previous_date.month}月{previous_date.day}日相比"


def _apply_comparison_reference(
    text: str,
    report: dict[str, object],
    previous: dict[str, object] | None,
) -> str:
    comparison_reference = _comparison_reference(report, previous)
    if comparison_reference == "与昨日相比":
        return text
    return text.replace("与昨日相比", comparison_reference).replace("较昨日相比", comparison_reference)


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
