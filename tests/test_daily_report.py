import asyncio
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from docx import Document
from starlette.requests import Request

from app.routers import api as api_router
from app.routers import daily_report as daily_report_router
from app.services.docx_generator import DAILY_REPORT_TEMPLATE, generate_daily_report_docx


class TrendComputationTests(TestCase):
    def setUp(self):
        # Replicate the trend computation logic from the router
        self.numeric_fields = [
            "waf_attacks", "waf_blocked", "waf_ips_banned",
            "cfw_attacks", "cfw_unblocked",
            "hss_alerts", "ddos_cleanings", "ddos_blackholes", "secmaster_alerts",
            "waf_detail_attacks", "waf_detail_blocked", "waf_qps_peak_value",
            "cfw_detail_attacks", "cfw_detail_unblocked",
            "hss_detail_total", "hss_detail_fatal", "hss_detail_high",
            "hss_detail_medium", "hss_detail_low",
            "hss_unclosed_event_count",
            "ddos_detail_cleanings", "ddos_detail_blackholes",
            "secmaster_detail_total", "secmaster_detail_fatal", "secmaster_detail_high",
            "secmaster_detail_medium", "secmaster_detail_low", "secmaster_detail_info",
            "secmaster_unclosed_event_count",
        ]

    def _compute_trends(self, current, previous):
        if previous is None:
            return {}
        trends = {}
        for field in self.numeric_fields:
            cur_val = int(current.get(field, 0))
            prev_val = int(previous.get(field, 0))
            change = cur_val - prev_val
            pct = round((change / prev_val) * 100, 1) if prev_val != 0 else None
            trends[field] = {"change": change, "percent": pct}
        return trends

    def test_no_previous_returns_empty(self):
        trends = self._compute_trends({"waf_attacks": 100}, None)
        self.assertEqual(trends, {})

    def test_increase_calculated_correctly(self):
        trends = self._compute_trends(
            {"waf_attacks": 150},
            {"waf_attacks": 100},
        )
        self.assertEqual(trends["waf_attacks"]["change"], 50)
        self.assertEqual(trends["waf_attacks"]["percent"], 50.0)

    def test_decrease_calculated_correctly(self):
        trends = self._compute_trends(
            {"waf_attacks": 80},
            {"waf_attacks": 100},
        )
        self.assertEqual(trends["waf_attacks"]["change"], -20)
        self.assertEqual(trends["waf_attacks"]["percent"], -20.0)

    def test_zero_previous_returns_none_percent(self):
        trends = self._compute_trends(
            {"waf_attacks": 10},
            {"waf_attacks": 0},
        )
        self.assertEqual(trends["waf_attacks"]["change"], 10)
        self.assertIsNone(trends["waf_attacks"]["percent"])

    def test_missing_fields_treated_as_zero(self):
        trends = self._compute_trends(
            {"waf_attacks": 50},
            {},
        )
        self.assertEqual(trends["waf_attacks"]["change"], 50)
        self.assertIsNone(trends["waf_attacks"]["percent"])


class DocxGenerationTests(TestCase):
    def _normalized_xml(self, element) -> str:
        if element is None:
            return ""
        return re.sub(r">\s+<", "><", element.xml).strip()

    def _paragraph_snapshot(self, paragraph):
        paragraph_format = paragraph.paragraph_format
        first_run = paragraph.runs[0] if paragraph.runs else None
        return {
            "style": paragraph.style.name if paragraph.style else None,
            "alignment": paragraph.alignment,
            "left_indent": paragraph_format.left_indent.pt if paragraph_format.left_indent else None,
            "first_line_indent": paragraph_format.first_line_indent.pt if paragraph_format.first_line_indent else None,
            "space_before": paragraph_format.space_before.pt if paragraph_format.space_before else None,
            "space_after": paragraph_format.space_after.pt if paragraph_format.space_after else None,
            "font_name": first_run.font.name if first_run else None,
            "font_size": first_run.font.size.pt if first_run and first_run.font.size else None,
            "bold": first_run.bold if first_run else None,
        }

    def _paragraph_style_signature(self, paragraph):
        paragraph_format = paragraph.paragraph_format
        runs = []
        for run in paragraph.runs:
            if run.text or len(paragraph.runs) == 1:
                runs.append(
                    {
                        "font_name": (run.font.name or "").replace(" ", ""),
                        "font_size": run.font.size.pt if run.font.size else None,
                        "bold": run.bold,
                        "italic": run.italic,
                        "underline": run.underline,
                    }
                )
        return {
            "style": paragraph.style.name if paragraph.style else None,
            "alignment": paragraph.alignment,
            "left_indent": paragraph_format.left_indent.pt if paragraph_format.left_indent else None,
            "first_line_indent": paragraph_format.first_line_indent.pt if paragraph_format.first_line_indent else None,
            "space_before": paragraph_format.space_before.pt if paragraph_format.space_before else None,
            "space_after": paragraph_format.space_after.pt if paragraph_format.space_after else None,
            "line_spacing": paragraph_format.line_spacing,
            "runs": runs,
        }

    def _paragraph_structure_signature(self, paragraph):
        paragraph_format = paragraph.paragraph_format
        return {
            "style": paragraph.style.name if paragraph.style else None,
            "alignment": paragraph.alignment,
            "left_indent": paragraph_format.left_indent.pt if paragraph_format.left_indent else None,
            "right_indent": paragraph_format.right_indent.pt if paragraph_format.right_indent else None,
            "first_line_indent": paragraph_format.first_line_indent.pt if paragraph_format.first_line_indent else None,
            "space_before": paragraph_format.space_before.pt if paragraph_format.space_before else None,
            "space_after": paragraph_format.space_after.pt if paragraph_format.space_after else None,
            "line_spacing": paragraph_format.line_spacing,
            "line_spacing_rule": str(paragraph_format.line_spacing_rule),
        }

    def _cell_layout_signatures(self, cell):
        return [self._paragraph_structure_signature(paragraph) for paragraph in cell.paragraphs]

    def _run_format_signature(self, run):
        return {
            "rpr": self._normalized_xml(run._element.rPr),
            "drawing_count": len(run._element.xpath('.//*[local-name()="drawing"]')),
            "br_count": len(run._element.xpath('.//*[local-name()="br"]')),
            "tab_count": len(run._element.xpath('.//*[local-name()="tab"]')),
        }

    def _paragraph_format_signature(self, paragraph):
        return {
            "ppr": self._normalized_xml(paragraph._element.pPr),
            "runs": [self._run_format_signature(run) for run in paragraph.runs],
        }

    def _cell_format_signature(self, cell):
        return {
            "tcpr": self._normalized_xml(cell._tc.tcPr),
            "paragraphs": [self._paragraph_format_signature(paragraph) for paragraph in cell.paragraphs],
            "tables": [self._table_format_signature(table) for table in cell.tables],
        }

    def _row_format_signature(self, row):
        return {
            "trpr": self._normalized_xml(row._tr.trPr),
            "cells": [self._cell_format_signature(cell) for cell in row.cells],
        }

    def _table_format_signature(self, table):
        return {
            "tblpr": self._normalized_xml(table._tbl.tblPr),
            "tblgrid": self._normalized_xml(table._tbl.tblGrid),
            "rows": [self._row_format_signature(row) for row in table.rows],
        }

    def _section_format_signature(self, section):
        section_properties = section._sectPr
        return {
            "sectpr": self._normalized_xml(section_properties),
            "header_paragraphs": [self._paragraph_format_signature(paragraph) for paragraph in section.header.paragraphs],
            "footer_paragraphs": [self._paragraph_format_signature(paragraph) for paragraph in section.footer.paragraphs],
        }

    def _document_format_signature(self, document):
        return {
            "sections": [self._section_format_signature(section) for section in document.sections],
            "body_paragraphs": [self._paragraph_format_signature(paragraph) for paragraph in document.paragraphs],
            "tables": [self._table_format_signature(table) for table in document.tables],
        }

    def test_generates_docx_file(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "暂无",
            "key_work_content": "暂无",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.suffix, ".docx")
            self.assertIn("2026-05-21", file_path.name)

    def test_top_banner_fits_first_table_cell(self):
        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx({"report_date": "2026-05-21"}, [])

            with ZipFile(file_path) as docx_zip:
                document_root = ET.fromstring(docx_zip.read("word/document.xml"))

        namespaces = {
            "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
            "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        word_namespace = namespaces["w"]
        first_table = document_root.find(".//w:tbl", namespaces)
        self.assertIsNotNone(first_table)

        table_width = first_table.find("./w:tblPr/w:tblW", namespaces)
        table_indent = first_table.find("./w:tblPr/w:tblInd", namespaces)
        table_layout = first_table.find("./w:tblPr/w:tblLayout", namespaces)
        grid_column = first_table.find("./w:tblGrid/w:gridCol", namespaces)
        outer_cells = first_table.findall("./w:tr/w:tc", namespaces)
        self.assertIsNotNone(table_width)
        self.assertIsNotNone(table_indent)
        self.assertIsNotNone(table_layout)
        self.assertIsNotNone(grid_column)
        self.assertTrue(outer_cells)

        first_cell = outer_cells[0]
        banner_anchor = first_cell.find(".//wp:anchor", namespaces)
        self.assertIsNotNone(banner_anchor)

        layout_extent = banner_anchor.find("./wp:extent", namespaces)
        graphic_extent = banner_anchor.find(".//a:xfrm/a:ext", namespaces)
        self.assertIsNotNone(layout_extent)
        self.assertIsNotNone(graphic_extent)

        width_attribute = f"{{{word_namespace}}}w"
        type_attribute = f"{{{word_namespace}}}type"
        table_width_dxa = int(table_width.attrib[width_attribute])
        self.assertEqual(table_width.attrib[type_attribute], "dxa")
        self.assertEqual(table_indent.attrib, {width_attribute: "0", type_attribute: "dxa"})
        self.assertEqual(table_layout.attrib[type_attribute], "fixed")
        self.assertEqual(int(grid_column.attrib[width_attribute]), table_width_dxa)
        for cell in outer_cells:
            cell_width = cell.find("./w:tcPr/w:tcW", namespaces)
            self.assertIsNotNone(cell_width)
            self.assertEqual(int(cell_width.attrib[width_attribute]), table_width_dxa)

        self.assertEqual(int(layout_extent.attrib["cx"]), table_width_dxa * 635)
        self.assertEqual(layout_extent.attrib["cx"], graphic_extent.attrib["cx"])
        self.assertEqual(layout_extent.attrib["cy"], graphic_extent.attrib["cy"])

    def test_report_table_uses_expanded_page_width(self):
        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx({"report_date": "2026-07-27"}, [])

            with ZipFile(file_path) as docx_zip:
                document_root = ET.fromstring(docx_zip.read("word/document.xml"))

        namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        word_namespace = namespaces["w"]
        width_attribute = f"{{{word_namespace}}}w"
        page_size = document_root.find(".//w:sectPr/w:pgSz", namespaces)
        page_margins = document_root.find(".//w:sectPr/w:pgMar", namespaces)
        table_width = document_root.find(".//w:tbl/w:tblPr/w:tblW", namespaces)

        self.assertIsNotNone(page_size)
        self.assertIsNotNone(page_margins)
        self.assertIsNotNone(table_width)
        left_margin = int(page_margins.attrib[f"{{{word_namespace}}}left"])
        right_margin = int(page_margins.attrib[f"{{{word_namespace}}}right"])
        usable_width = int(page_size.attrib[width_attribute]) - left_margin - right_margin
        self.assertLess(left_margin, 720)
        self.assertLess(right_margin, 720)
        self.assertGreater(usable_width, 9922)
        self.assertEqual(int(table_width.attrib[width_attribute]), usable_width)

    def test_template_omits_empty_tail_paragraph(self):
        with ZipFile(DAILY_REPORT_TEMPLATE) as docx_zip:
            document_root = ET.fromstring(docx_zip.read("word/document.xml"))

        namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        body = document_root.find("./w:body", namespaces)
        self.assertIsNotNone(body)
        child_tags = [child.tag.rsplit("}", 1)[-1] for child in list(body)]
        self.assertEqual(child_tags, ["tbl", "sectPr"])

    def test_updates_header_title_with_report_date(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            with ZipFile(file_path) as docx_zip:
                core_xml = docx_zip.read("docProps/core.xml").decode("utf-8")
                header_xml = docx_zip.read("word/header2.xml").decode("utf-8")

        expected_title = "比亚迪规划院安全运营日报-2026年5月21日"
        stale_title = "比亚迪规划院安全运营日报-2026年5月20日"

        self.assertIn(f"<dc:title>{expected_title}</dc:title>", core_xml)
        self.assertIn(expected_title, header_xml)
        self.assertNotIn(stale_title, core_xml)
        self.assertNotIn(stale_title, header_xml)

    def test_footer_uses_report_date_instead_of_generation_time(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            with ZipFile(file_path) as docx_zip:
                footer_xml = docx_zip.read("word/footer2.xml").decode("utf-8")

        self.assertIn("2026-05-21", footer_xml)
        self.assertNotIn(" TIME ", footer_xml)

    def test_generates_docx_with_screenshot_paths(self):
        png_bytes = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000D49444154789C6360606060000000050001A5F645400000000049454E44AE426082"
        )
        with TemporaryDirectory() as temp_dir:
            screenshot_dir = Path(temp_dir) / "shots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = screenshot_dir / "waf.png"
            screenshot_path.write_bytes(png_bytes)

            report = {
                "report_date": "2026-05-21",
                "waf_screenshot_path": str(screenshot_path),
                "business_stability": "稳定",
            }

            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            self.assertTrue(file_path.exists())

    def test_populates_template_fixed_sections(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "key_work_content": "今日已完成重点巡检。",
            "legacy_items": "攻击路径分析暂无异常。",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            doc = Document(file_path)
            table = doc.tables[0]

            self.assertEqual(table.rows[2].cells[0].paragraphs[0].text, "今日业务运行稳定。")
            self.assertIn("WAF遭受攻击1000次", table.rows[2].cells[0].paragraphs[1].text)
            self.assertIn("有12个事件未闭环", table.rows[2].cells[0].paragraphs[1].text)
            self.assertIn("有8个事件未闭环", table.rows[2].cells[0].paragraphs[1].text)
            self.assertIn("趋势平稳。总体态势良好。", table.rows[2].cells[0].paragraphs[2].text)
            self.assertIn("监控时间：2026年5月20日 18:00~2026年5月21日 18:00", table.rows[3].cells[0].paragraphs[0].text)
            self.assertIn("入方向流量峰值15.90Gbps", table.rows[4].cells[0].paragraphs[10].text)
            self.assertIn("入方向95带宽值14.71Gbps", table.rows[4].cells[0].paragraphs[10].text)
            self.assertIn("未闭环事件12个", table.rows[4].cells[0].paragraphs[13].text)
            self.assertIn("未闭环事件8个", table.rows[4].cells[0].paragraphs[20].text)
            self.assertEqual(table.rows[6].cells[0].paragraphs[0].text, "今日已完成重点巡检。")
            self.assertEqual(table.rows[8].cells[0].paragraphs[0].text, "攻击路径分析暂无异常。")

            operator_table = table.rows[10].cells[0].tables[0]
            self.assertEqual(len(operator_table.rows), 5)
            self.assertEqual(operator_table.rows[1].cells[1].text, "张三")
            self.assertEqual(operator_table.rows[1].cells[4].text, "负责安全监控。")
            self.assertEqual(operator_table.rows[2].cells[1].text, "")

    def test_cfw_bandwidth_detail_adds_fixed_gbps_unit_from_template(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90",
            "cfw_inbound_95th": "14.71Gbps",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            doc = Document(file_path)
            paragraph_text = doc.tables[0].rows[4].cells[0].paragraphs[10].text

        self.assertIn("入方向流量峰值15.90Gbps", paragraph_text)
        self.assertIn("入方向95带宽值14.71Gbps", paragraph_text)
        self.assertNotIn("GbpsGbps", paragraph_text)

    def test_generates_all_configured_operators_beyond_template_capacity(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
        }
        operators = [
            {
                "name": f"运营人员{index}",
                "phone": f"1380013800{index}",
                "role": f"角色{index}",
                "responsibility": "负责安全监控。",
            }
            for index in range(1, 8)
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            doc = Document(file_path)
            operator_table = doc.tables[0].rows[10].cells[0].tables[0]

        self.assertEqual(len(operator_table.rows), 8)
        for index, operator in enumerate(operators, start=1):
            row = operator_table.rows[index]
            self.assertEqual(row.cells[1].text, operator["name"])
            self.assertEqual(row.cells[2].text, operator["phone"])
            self.assertEqual(row.cells[3].text, operator["role"])
        self.assertEqual(operator_table.rows[1].cells[4].text, "负责安全监控。")

    def test_waf_qps_caption_is_separate_from_embedded_picture(self):
        doc = Document(DAILY_REPORT_TEMPLATE)
        image_paragraph = doc.tables[0].rows[4].cells[0].paragraphs[5]
        caption_paragraph = doc.tables[0].rows[4].cells[0].paragraphs[6]

        drawing_count = len(image_paragraph._element.xpath('.//*[local-name()="drawing"]'))
        break_count = len(image_paragraph._element.xpath('.//*[local-name()="br"]'))

        self.assertEqual(image_paragraph.text, "\n")
        self.assertEqual(caption_paragraph.text, "图2：\u00a0WAF监测QPS趋势情况（单位：qps）")
        self.assertGreater(drawing_count, 0)
        self.assertGreater(break_count, 0)

    def test_preserves_template_paragraph_formatting(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            template = Document(DAILY_REPORT_TEMPLATE)
            generated = Document(file_path)

            paragraph_positions = [(2, 0), (2, 1), (2, 2), (3, 0), (4, 1), (6, 0)]
            for row_index, paragraph_index in paragraph_positions:
                template_paragraph = template.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                generated_paragraph = generated.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                self.assertEqual(
                    self._paragraph_snapshot(generated_paragraph),
                    self._paragraph_snapshot(template_paragraph),
                )

            key_work_paragraph = generated.tables[0].rows[8].cells[0].paragraphs[0]
            self.assertEqual((key_work_paragraph.runs[0].font.name or "").replace(" ", ""), "微软雅黑")

    def test_preserves_template_styles_for_all_replaced_sections(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
            {"name": "李四", "phone": "13900139000", "role": "项目PM", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            template = Document(DAILY_REPORT_TEMPLATE)
            generated = Document(file_path)

            paragraph_positions = [
                (3, 0),
                (4, 0),
                (4, 1),
                (4, 4),
                (4, 7),
                (4, 10),
                (4, 13),
                (4, 17),
                (4, 20),
                (4, 23),
                (4, 24),
                (6, 0),
            ]
            for row_index, paragraph_index in paragraph_positions:
                template_paragraph = template.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                generated_paragraph = generated.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                self.assertEqual(
                    self._paragraph_style_signature(generated_paragraph),
                    self._paragraph_style_signature(template_paragraph),
                )

            template_key_work = template.tables[0].rows[8].cells[0].paragraphs[0]
            generated_key_work = generated.tables[0].rows[8].cells[0].paragraphs[0]
            self.assertEqual(
                self._paragraph_structure_signature(generated_key_work),
                self._paragraph_structure_signature(template_key_work),
            )
            for run in generated_key_work.runs:
                if run.text:
                    self.assertEqual((run.font.name or "").replace(" ", ""), "微软雅黑")

            template_operator_table = template.tables[0].rows[10].cells[0].tables[0]
            generated_operator_table = generated.tables[0].rows[10].cells[0].tables[0]
            operator_cells = [(1, 0), (1, 1), (1, 2), (1, 3), (1, 4)]
            for row_index, cell_index in operator_cells:
                template_paragraph = template_operator_table.rows[row_index].cells[cell_index].paragraphs[0]
                generated_paragraph = generated_operator_table.rows[row_index].cells[cell_index].paragraphs[0]
                self.assertEqual(
                    self._paragraph_style_signature(generated_paragraph),
                    self._paragraph_style_signature(template_paragraph),
                )

    def test_body_paragraphs_use_microsoft_yahei(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            doc = Document(file_path)
            paragraph_positions = [
                (2, 0),
                (2, 1),
                (2, 2),
                (4, 1),
                (4, 4),
                (4, 7),
                (4, 10),
                (4, 13),
                (4, 17),
                (4, 20),
                (4, 24),
                (6, 0),
                (8, 0),
            ]
            for row_index, paragraph_index in paragraph_positions:
                paragraph = doc.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                for run in paragraph.runs:
                    if run.text.strip():
                        self.assertEqual((run.font.name or "").replace(" ", ""), "微软雅黑")

    def test_figure_captions_preserve_template_formatting(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            template = Document(DAILY_REPORT_TEMPLATE)
            generated = Document(file_path)
            caption_positions = [(4, 3), (4, 6), (4, 9), (4, 12), (4, 16), (4, 19), (4, 22)]

            for row_index, paragraph_index in caption_positions:
                template_paragraph = template.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                generated_paragraph = generated.tables[0].rows[row_index].cells[0].paragraphs[paragraph_index]
                self.assertEqual(
                    self._paragraph_style_signature(generated_paragraph),
                    self._paragraph_style_signature(template_paragraph),
                )
                for run in generated_paragraph.runs:
                    if run.text.strip():
                        self.assertEqual((run.font.name or "").replace(" ", ""), "宋体")

    def test_preserves_template_layout_for_full_report_regions(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
            {"name": "李四", "phone": "13900139000", "role": "项目PM", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            template = Document(DAILY_REPORT_TEMPLATE)
            generated = Document(file_path)

            for row_index in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11):
                template_cell = template.tables[0].rows[row_index].cells[0]
                generated_cell = generated.tables[0].rows[row_index].cells[0]
                self.assertEqual(
                    self._cell_layout_signatures(generated_cell),
                    self._cell_layout_signatures(template_cell),
                )

            template_operator_table = template.tables[0].rows[10].cells[0].tables[0]
            generated_operator_table = generated.tables[0].rows[10].cells[0].tables[0]
            for row_index in range(len(template_operator_table.rows)):
                for cell_index in range(len(template_operator_table.columns)):
                    template_cell = template_operator_table.rows[row_index].cells[cell_index]
                    generated_cell = generated_operator_table.rows[row_index].cells[cell_index]
                    self.assertEqual(
                        self._cell_layout_signatures(generated_cell),
                        self._cell_layout_signatures(template_cell),
                    )

    def test_preserves_full_document_format_signature(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
            "waf_attacks": 1000,
            "waf_blocked": 900,
            "waf_ips_banned": 5,
            "cfw_attacks": 500,
            "cfw_unblocked": 2,
            "hss_alerts": 100,
            "ddos_cleanings": 0,
            "ddos_blackholes": 0,
            "secmaster_alerts": 50,
            "trend_comparison": "趋势平稳。",
            "overall_assessment": "总体态势良好。",
            "monitor_start": "2026-05-20 18:00",
            "monitor_end": "2026-05-21 18:00",
            "waf_detail_attacks": 1000,
            "waf_detail_blocked": 900,
            "waf_qps_specs": "85,000",
            "waf_qps_peak_range": "17:00-18:00",
            "waf_qps_peak_value": 178848,
            "waf_exceeded_spec": 1,
            "cfw_detail_attacks": 500,
            "cfw_detail_unblocked": 2,
            "cfw_bandwidth_spec": "12050Mbps",
            "cfw_peak_inbound_range": "16:44-18:00",
            "cfw_inbound_peak": "15.90Gbps",
            "cfw_inbound_95th": "14.71Gbps",
            "cfw_exceeded_spec": 1,
            "hss_detail_total": 100,
            "hss_detail_fatal": 0,
            "hss_detail_high": 20,
            "hss_detail_medium": 30,
            "hss_detail_low": 50,
            "hss_unclosed_event_count": 12,
            "hss_closed_loop_status": "已全部闭环。",
            "ddos_detail_cleanings": 0,
            "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 50,
            "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0,
            "secmaster_detail_medium": 50,
            "secmaster_detail_low": 0,
            "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 8,
            "emergency_response": "无。",
            "legacy_items": "攻击路径分析暂无异常。",
            "key_work_content": "今日已完成重点巡检。",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
            {"name": "李四", "phone": "13900139000", "role": "项目PM", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            template = Document(DAILY_REPORT_TEMPLATE)
            generated = Document(file_path)

            self.assertEqual(
                self._document_format_signature(generated),
                self._document_format_signature(template),
            )

    def test_handles_empty_operators(self):
        report = {
            "report_date": "2026-05-21",
            "waf_attacks": 0, "waf_blocked": 0, "waf_ips_banned": 0,
            "cfw_attacks": 0, "cfw_unblocked": 0,
            "hss_alerts": 0, "ddos_cleanings": 0, "ddos_blackholes": 0,
            "secmaster_alerts": 0,
            "waf_detail_attacks": 0, "waf_detail_blocked": 0,
            "waf_qps_specs": "", "waf_qps_peak_range": "", "waf_qps_peak_value": 0,
            "waf_exceeded_spec": 0,
            "cfw_detail_attacks": 0, "cfw_detail_unblocked": 0,
            "cfw_bandwidth_spec": "", "cfw_peak_inbound_range": "",
            "cfw_inbound_peak": "", "cfw_inbound_95th": "", "cfw_exceeded_spec": 0,
            "hss_detail_total": 0, "hss_detail_fatal": 0,
            "hss_detail_high": 0, "hss_detail_medium": 0, "hss_detail_low": 0,
            "hss_unclosed_event_count": 0,
            "hss_closed_loop_status": "",
            "ddos_detail_cleanings": 0, "ddos_detail_blackholes": 0,
            "secmaster_detail_total": 0, "secmaster_detail_fatal": 0,
            "secmaster_detail_high": 0, "secmaster_detail_medium": 0,
            "secmaster_detail_low": 0, "secmaster_detail_info": 0,
            "secmaster_unclosed_event_count": 0,
            "business_stability": "", "trend_comparison": "", "overall_assessment": "",
            "monitor_start": "", "monitor_end": "",
            "emergency_response": "", "legacy_items": "", "key_work_content": "",
        }

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, [])

            self.assertTrue(file_path.exists())

    def test_operator_rows_use_uniform_exact_height(self):
        report = {
            "report_date": "2026-05-21",
            "business_stability": "今日业务运行稳定。",
        }
        operators = [
            {"name": "张三", "phone": "13800138000", "role": "安全运营人员", "responsibility": "负责安全监控。"},
            {"name": "李四", "phone": "13900139000", "role": "项目PM", "responsibility": "负责安全监控。"},
        ]

        with TemporaryDirectory() as temp_dir:
            with patch("app.services.docx_generator.EXPORT_DIR", Path(temp_dir)):
                file_path = generate_daily_report_docx(report, operators)

            doc = Document(file_path)
            operator_table = doc.tables[0].rows[10].cells[0].tables[0]

        for row in operator_table.rows[1:]:
            tr_height = row._tr.trPr.trHeight
            self.assertIsNotNone(tr_height)
            self.assertIn('w:val="280"', tr_height.xml)
            self.assertEqual(str(tr_height.hRule), "AT_LEAST (1)")


class DailyReportDateEchoTests(TestCase):
    def _request(self, path: str, query_string: str = "") -> Request:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string.encode(),
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "session": {},
        }
        return Request(scope)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_form_uses_query_date_for_echo(self):
        report_date = "2026-06-24"
        report = {
            "business_stability": "stable",
            "monitor_start": "2026-06-23 18:00",
            "monitor_end": "2026-06-24 18:00",
        }

        with (
            patch("app.routers.daily_report.require_login", return_value={"display_name": "Tester"}),
            patch("app.routers.daily_report.get_daily_report_by_date", return_value=report) as get_report,
            patch("app.routers.daily_report.get_previous_report", return_value=None),
            patch("app.routers.daily_report.list_ops_personnel", return_value=[]),
        ):
            response = self._run(
                daily_report_router.daily_report_form(
                    self._request("/daily-report", f"date={report_date}"),
                    date=report_date,
                )
            )

        html = response.template.render(response.context)
        self.assertEqual(response.status_code, 200)
        get_report.assert_called_once_with(report_date)
        self.assertIn(f'name="report_date" value="{report_date}"', html)
        self.assertIn(f'/daily-report/preview?date={report_date}', html)

    def test_save_redirects_back_to_same_date(self):
        report_date = "2026-06-24"
        form_data = {
            "report_date": report_date,
            "business_stability": "stable",
            "waf_detail_attacks": "12",
        }

        class FakeRequest:
            def __init__(self):
                self.session = {}

            async def form(self):
                return form_data

        with (
            patch("app.routers.daily_report.require_login", return_value={"display_name": "Tester"}),
            patch("app.routers.daily_report.get_daily_report_by_date", return_value={}),
            patch("app.routers.daily_report.save_daily_report") as save_report,
        ):
            response = self._run(
                daily_report_router.daily_report_save(
                    FakeRequest(),
                    report_date=report_date,
                )
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], f"/daily-report?date={report_date}")
        save_report.assert_called_once()
        self.assertEqual(save_report.call_args.args[0], report_date)

    def test_preview_links_keep_selected_date(self):
        report_date = "2026-06-24"

        with (
            patch("app.routers.daily_report.require_login", return_value={"display_name": "Tester"}),
            patch("app.routers.daily_report.get_daily_report_by_date", return_value={"report_date": report_date}),
        ):
            response = self._run(
                daily_report_router.daily_report_preview(
                    self._request("/daily-report/preview", f"date={report_date}"),
                    date=report_date,
                )
            )

        html = response.template.render(response.context)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/daily-report?date={report_date}', html)
        self.assertIn(f'/daily-report/download?date={report_date}', html)


class OperatorApiTests(TestCase):
    class _JsonRequest:
        def __init__(self, payload):
            self._payload = payload

        async def json(self):
            return self._payload

    def _run(self, coro):
        return asyncio.run(coro)

    def test_update_operator_passes_record_id_to_save(self):
        payload = {
            "name": "张三",
            "phone": "13800138000",
            "role": "安全运营人员",
            "responsibility": "负责安全监控。",
            "sort_order": 1,
        }

        with (
            patch("app.routers.api.require_login", return_value={"display_name": "Tester"}),
            patch("app.routers.api.db.save_ops_personnel") as save_ops_personnel,
        ):
            response = self._run(api_router.api_update_operator(self._JsonRequest(payload), 7))

        self.assertEqual(response, {"success": True})
        save_ops_personnel.assert_called_once_with(payload, 7)


class DailyReportEmailApiTests(TestCase):
    class _JsonRequest:
        def __init__(self, payload):
            self._payload = payload

        async def json(self):
            return self._payload

    def _run(self, coro):
        return asyncio.run(coro)

    def _endpoint(self):
        return next(
            route.endpoint
            for route in api_router.router.routes
            if getattr(route, "path", "") == "/api/daily-report/send-report-email"
        )

    def test_report_email_reuses_saved_smtp_settings_and_subject(self):
        settings = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_user": "sender@example.com",
            "smtp_password": "secret",
            "smtp_from": "",
            "use_tls": True,
            "daily_report_subject": "【安全运营日报】{date}",
        }
        payload = {
            "report_date": "2026-07-21",
            "to": "first@example.com,second@example.com",
            "cc": "copy@example.com",
            "subject": "",
        }
        docx_path = Path("daily-report.docx")

        with (
            patch("app.routers.api.require_login", return_value={"display_name": "Tester"}),
            patch("app.routers.api.db.get_daily_report_by_date", return_value={"report_date": "2026-07-21"}),
            patch("app.routers.api.db.list_ops_personnel", return_value=[]),
            patch("app.routers.api.db.get_email_settings", return_value=settings),
            patch("app.services.docx_generator.generate_daily_report_docx", return_value=docx_path),
            patch("app.routers.api._docx_to_html", return_value="<p>日报正文</p>"),
            patch("app.services.email_service.send_email", return_value={"success": True}) as send_email,
        ):
            response = self._run(self._endpoint()(self._JsonRequest(payload)))

        self.assertEqual(response, {"success": True})
        send_email.assert_called_once()
        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["to_list"], ["first@example.com", "second@example.com"])
        self.assertEqual(kwargs["cc_list"], ["copy@example.com"])
        self.assertEqual(kwargs["subject"], "【安全运营日报】2026年07月21日")
        self.assertIs(kwargs["smtp_config"], settings)
