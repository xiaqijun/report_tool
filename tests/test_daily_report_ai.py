from unittest import TestCase
from unittest.mock import patch

from app.services.daily_report_ai import _build_prompt, _build_trend_text, generate_top_section_text


class DailyReportAiTests(TestCase):
    def setUp(self):
        self.report = {
            "report_date": "2026-05-21",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_attacks": 100,
            "waf_blocked": 90,
            "waf_ips_banned": 5,
            "waf_qps_peak_value": 1500,
            "waf_exceeded_spec": False,
            "cfw_attacks": 20,
            "cfw_unblocked": 1,
            "cfw_inbound_peak": "120Mbps",
            "cfw_inbound_95th": "80Mbps",
            "cfw_exceeded_spec": False,
            "hss_alerts": 8,
            "hss_detail_fatal": 0,
            "hss_detail_high": 1,
            "hss_detail_medium": 2,
            "hss_detail_low": 5,
            "hss_unclosed_event_count": 2,
            "hss_closed_loop_status": "高危告警已完成核查",
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 6,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 1,
            "secmaster_detail_medium": 2,
            "secmaster_detail_low": 2,
            "secmaster_detail_info": 1,
            "secmaster_unclosed_event_count": 1,
        }
        self.previous = {
            "waf_attacks": 80,
            "waf_blocked": 70,
            "waf_ips_banned": 3,
            "cfw_attacks": 25,
            "cfw_unblocked": 2,
            "hss_alerts": 10,
            "hss_detail_fatal": 1,
            "hss_detail_high": 2,
            "secmaster_alerts": 6,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 1,
        }

    def test_fallback_generation_returns_three_fields(self):
        with patch("app.services.daily_report_ai.LLM_API_BASE_URL", ""), patch("app.services.daily_report_ai.LLM_API_KEY", ""), patch("app.services.daily_report_ai.LLM_MODEL", ""):
            result = generate_top_section_text(self.report, self.previous)

        self.assertEqual(set(result.keys()), {"business_stability", "trend_comparison", "overall_assessment"})
        self.assertTrue(result["business_stability"].startswith("今日业务运行稳定"))
        self.assertTrue(result["trend_comparison"].startswith("与昨日相比"))
        self.assertTrue(result["overall_assessment"].startswith("总体来看"))

    def test_can_generate_single_field(self):
        with patch("app.services.daily_report_ai.LLM_API_BASE_URL", ""), patch("app.services.daily_report_ai.LLM_API_KEY", ""), patch("app.services.daily_report_ai.LLM_MODEL", ""):
            result = generate_top_section_text(self.report, self.previous, fields=("overall_assessment",))

        self.assertEqual(set(result.keys()), {"overall_assessment"})
        self.assertTrue(result["overall_assessment"].startswith("总体来看"))

    def test_llm_result_overrides_fallback_when_available(self):
        expected = {
            "business_stability": "模型生成的业务运行情况。",
            "trend_comparison": "模型生成的趋势对比说明，可能与攻击活跃度变化有关。",
            "overall_assessment": "模型生成的总体评估。",
        }
        with patch("app.services.daily_report_ai.LLM_API_BASE_URL", "https://example.com/v1"), patch("app.services.daily_report_ai.LLM_API_KEY", "key"), patch("app.services.daily_report_ai.LLM_MODEL", "model"), patch("app.services.daily_report_ai._call_llm", return_value=expected):
            result = generate_top_section_text(self.report, self.previous)

        self.assertEqual(result, expected)

    def test_prompt_is_tightened_for_single_field_tone(self):
        prompt = _build_prompt(self.report, self.previous, ("trend_comparison",))

        self.assertIn("只写1句话", prompt)
        self.assertIn("必须使用‘与昨日相比，’起句", prompt)
        self.assertIn("避免逐项罗列具体增减值", prompt)
        self.assertIn("正式、简洁、稳健", prompt)
        self.assertIn("分析变化原因", prompt)
        self.assertIn("原因只能依据所提供的辅助指标", prompt)
        self.assertIn("具体原因暂无法确认", prompt)
        self.assertIn('"hss_detail_high": 1', prompt)

    def test_prompt_includes_historical_style_examples(self):
        prompt = _build_prompt(self.report, self.previous, ("business_stability", "overall_assessment"))

        self.assertIn("今日业务运行稳定，无主机入侵事件，整体安全状态稳定。", prompt)
        self.assertIn("总体来看，整体安全态势保持平稳可控。", prompt)

    def test_trend_fallback_uses_grouped_summary_style(self):
        text = _build_trend_text(self.report, self.previous)

        self.assertTrue(
            text.startswith(
                "与昨日相比，CFW攻击数量、HSS告警数量均有所下降，WAF攻击数量有所上升，SecMaster告警数量基本持平；"
            )
        )
        self.assertIn("不同攻击面的活跃度变化", text)
        self.assertIn("主机异常行为及高风险规则命中减少", text)
        self.assertIn("进一步核实", text)
        self.assertNotIn("整体波动处于预期范围内", text)

    def test_trend_fallback_merges_metrics_with_similar_decline(self):
        report = {
            **self.report,
            "waf_attacks": 82,
            "cfw_attacks": 25,
            "hss_alerts": 8,
            "secmaster_alerts": 7,
        }
        previous = {
            "waf_attacks": 100,
            "cfw_attacks": 25,
            "hss_alerts": 10,
            "secmaster_alerts": 6,
        }

        text = _build_trend_text(report, previous)

        self.assertTrue(
            text.startswith(
                "与昨日相比，WAF攻击数量、HSS告警数量均有所下降，SecMaster告警数量有所上升，CFW攻击数量基本持平；"
            )
        )
        self.assertIn("外部扫描及网络攻击活跃度下降", text)
        self.assertIn("不同安全规则的命中结构变化", text)

    def test_trend_fallback_uses_stable_phrase_when_all_metrics_flat(self):
        previous = {
            "waf_attacks": self.report["waf_attacks"],
            "cfw_attacks": self.report["cfw_attacks"],
            "hss_alerts": self.report["hss_alerts"],
            "secmaster_alerts": self.report["secmaster_alerts"],
        }

        text = _build_trend_text(self.report, previous)

        self.assertTrue(text.startswith("与昨日相比，各项核心攻击与告警指标整体持平，暂无明显波动；"))
        self.assertIn("具体原因暂无法确认", text)

    def test_trend_fallback_analyzes_reasons_when_all_metrics_decline(self):
        report = {
            **self.report,
            "waf_attacks": 20,
            "waf_blocked": 18,
            "waf_ips_banned": 1,
            "cfw_attacks": 5,
            "cfw_unblocked": 0,
            "hss_alerts": 2,
            "hss_detail_fatal": 0,
            "hss_detail_high": 0,
            "secmaster_alerts": 1,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
        }
        previous = {
            **self.previous,
            "report_date": "2026-07-31",
            "waf_attacks": 100,
            "waf_blocked": 90,
            "waf_ips_banned": 8,
            "cfw_attacks": 40,
            "cfw_unblocked": 3,
            "hss_alerts": 12,
            "hss_detail_fatal": 1,
            "hss_detail_high": 4,
            "secmaster_alerts": 10,
            "secmaster_detail_fatal": 1,
            "secmaster_detail_high": 3,
        }
        report["report_date"] = "2026-08-03"

        text = _build_trend_text(report, previous)

        self.assertTrue(text.startswith("与7月31日相比，"))
        self.assertIn("外部扫描及网络攻击活跃度下降", text)
        self.assertIn("主机异常行为及高风险规则命中减少", text)
        self.assertIn("具体原因仍需结合攻击源、规则命中和业务变更信息进一步核实", text)

    def test_llm_trend_without_reason_is_completed_with_reason_analysis(self):
        expected = {
            "trend_comparison": "与昨日相比，WAF、CFW、HSS及SecMaster指标均有所下降，整体波动处于预期范围内。",
        }
        with (
            patch("app.services.daily_report_ai.LLM_API_BASE_URL", "https://example.com/v1"),
            patch("app.services.daily_report_ai.LLM_API_KEY", "key"),
            patch("app.services.daily_report_ai.LLM_MODEL", "model"),
            patch("app.services.daily_report_ai._call_llm", return_value=expected),
        ):
            result = generate_top_section_text(
                self.report,
                self.previous,
                fields=("trend_comparison",),
            )

        self.assertIn("具体原因仍需结合攻击源、规则命中和业务变更信息进一步核实", result["trend_comparison"])

    def test_trend_uses_previous_report_date_after_non_working_days(self):
        report = {**self.report, "report_date": "2026-07-27"}
        previous = {**self.previous, "report_date": "2026-07-24"}

        text = _build_trend_text(report, previous)
        prompt = _build_prompt(report, previous, ("trend_comparison",))

        self.assertTrue(text.startswith("与7月24日相比，"))
        self.assertIn("与7月24日相比", prompt)
        self.assertNotIn("昨日数据", prompt)

    def test_llm_yesterday_wording_is_corrected_for_previous_report_date(self):
        report = {**self.report, "report_date": "2026-10-09"}
        previous = {**self.previous, "report_date": "2026-09-30"}
        expected = {
            "business_stability": "今日业务运行稳定。",
            "trend_comparison": "与昨日相比，各项指标整体平稳。",
            "overall_assessment": "总体来看，安全态势平稳可控。",
        }
        with (
            patch("app.services.daily_report_ai.LLM_API_BASE_URL", "https://example.com/v1"),
            patch("app.services.daily_report_ai.LLM_API_KEY", "key"),
            patch("app.services.daily_report_ai.LLM_MODEL", "model"),
            patch("app.services.daily_report_ai._call_llm", return_value=expected),
        ):
            result = generate_top_section_text(report, previous)

        self.assertTrue(result["trend_comparison"].startswith("与9月30日相比，"))
