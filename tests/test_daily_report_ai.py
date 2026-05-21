from unittest import TestCase
from unittest.mock import patch

from app.services.daily_report_ai import _build_prompt, generate_top_section_text


class DailyReportAiTests(TestCase):
    def setUp(self):
        self.report = {
            "report_date": "2026-05-21",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_attacks": 100,
            "waf_blocked": 90,
            "waf_ips_banned": 5,
            "cfw_attacks": 20,
            "cfw_unblocked": 1,
            "hss_alerts": 8,
            "hss_unclosed_event_count": 2,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 6,
            "secmaster_unclosed_event_count": 1,
        }
        self.previous = {
            "waf_attacks": 80,
            "cfw_attacks": 25,
            "hss_alerts": 10,
            "secmaster_alerts": 6,
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
            "trend_comparison": "模型生成的趋势对比说明。",
            "overall_assessment": "模型生成的总体评估。",
        }
        with patch("app.services.daily_report_ai.LLM_API_BASE_URL", "https://example.com/v1"), patch("app.services.daily_report_ai.LLM_API_KEY", "key"), patch("app.services.daily_report_ai.LLM_MODEL", "model"), patch("app.services.daily_report_ai._call_llm", return_value=expected):
            result = generate_top_section_text(self.report, self.previous)

        self.assertEqual(result, expected)

    def test_prompt_is_tightened_for_single_field_tone(self):
        prompt = _build_prompt(self.report, self.previous, ("trend_comparison",))

        self.assertIn("只写1句话", prompt)
        self.assertIn("必须使用‘与昨日相比，’起句", prompt)
        self.assertIn("正式、简洁、稳健", prompt)
        self.assertIn("整体波动处于预期范围内", prompt)

    def test_prompt_includes_historical_style_examples(self):
        prompt = _build_prompt(self.report, self.previous, ("business_stability", "overall_assessment"))

        self.assertIn("今日业务运行稳定，无主机入侵事件，整体安全状态稳定。", prompt)
        self.assertIn("总体来看，整体安全态势保持平稳可控。", prompt)