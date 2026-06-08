"""Email service for sending daily security reports."""

import smtplib
import ssl
import base64
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional
from collections import Counter

from app.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_TLS


BASE_DIR = Path(__file__).resolve().parent.parent.parent
EMBEDDED_TEMPLATE_PATH = Path(__file__).resolve().parent / "email_template.html"
EMAIL_IMAGES_DIR = BASE_DIR / "app" / "static" / "email-images"


def _load_embedded_template() -> str:
    """Load the embedded HTML email template with images embedded as base64."""
    if not EMBEDDED_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Email template not found: {EMBEDDED_TEMPLATE_PATH}")
    with open(EMBEDDED_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    # Embed images as base64 data URIs
    def replace_cid(match):
        cid = match.group(1)
        if EMAIL_IMAGES_DIR.exists():
            for img_file in EMAIL_IMAGES_DIR.iterdir():
                if img_file.name.startswith(cid):
                    ext = img_file.suffix.lower()
                    mime_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif'}
                    mime = mime_map.get(ext, 'image/png')
                    with open(img_file, 'rb') as f:
                        b64_data = base64.b64encode(f.read()).decode()
                    return f'src="data:{mime};base64,{b64_data}"'
        return match.group(0)

    template = re.sub(r'src="cid:([^"]+)"', replace_cid, template)
    return template


def generate_email_from_report(
    report_date: str,
    protection_interrupted: list[dict],
    agent_missing: list[dict],
    online_unprotected: list[dict],
    recipient_names: list[str] | None = None,
    week_changes: dict | None = None,
    prev_protection_interrupted: list[dict] | None = None,
    prev_agent_missing: list[dict] | None = None,
    prev_online_unprotected: list[dict] | None = None,
) -> str:
    """
    Generate email HTML from report data using the original template format.
    Preserves the original HTML structure and only replaces data values.
    """
    template = _load_embedded_template()

    # Extract totals from data
    def extract_total(data_list):
        # First try to find "合计" or "总计" row (aggregated data)
        for row in data_list:
            if row.get("负责人") in ("合计", "总计"):
                val = row.get("服务器ID计数")
                if val is not None and str(val).strip():
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        pass
        # Fallback: count rows excluding 合计/总计 (raw host data)
        count = 0
        for row in data_list:
            if row.get("负责人") not in ("合计", "总计"):
                count += 1
        return count if count > 0 else len(data_list)

    interrupted_total = extract_total(protection_interrupted)
    missing_total = extract_total(agent_missing)
    unquota_total = extract_total(online_unprotected)

    # Update summary numbers in text - handle HTML tags around numbers
    template = re.sub(
        r'防护状态中断，共(<[^>]*>)*\d+(<[^>]*>)*台机器',
        f'防护状态中断，共{interrupted_total}台机器',
        template
    )
    template = re.sub(
        r'刨除暂不安装的剩余(<[^>]*>)*\d+(<[^>]*>)*台机器需要安装',
        f'刨除暂不安装的剩余{missing_total}台机器需要安装',
        template
    )
    template = re.sub(
        r'涉及到(<[^>]*>)*\d+(<[^>]*>)*台服务器',
        f'涉及到{unquota_total}台服务器',
        template
    )

    # Week-over-week comparison text will be updated after table updates
    # (using visible table changes for consistency)

    # Pre-load arrow images as base64 for table comparison indicators
    def _get_arrow_src(direction):
        """Get base64 data URI for arrow image (up=red increase, down=green decrease)."""
        if direction == 'up':
            target = '221FDF4D@2CFE3B37.98901F6A00000000.png'
        else:
            target = '53B5AE37@F9669E48.98901F6A00000000.png'
        if EMAIL_IMAGES_DIR.exists():
            for img_file in EMAIL_IMAGES_DIR.iterdir():
                if img_file.name.startswith(target):
                    ext = img_file.suffix.lower()
                    mime_map = {'.png': 'image/png', '.jpg': 'image/jpeg'}
                    mime = mime_map.get(ext, 'image/png')
                    with open(img_file, 'rb') as f:
                        b64_data = base64.b64encode(f.read()).decode()
                    return f'data:{mime};base64,{b64_data}'
        return ''

    arrow_up_src = _get_arrow_src('up')
    arrow_down_src = _get_arrow_src('down')

    # Update table data - generate rows directly from data (not template name matching)
    def update_table_data(html, table_id, data_list, total, prev_data_list=None):
        """Generate table rows from data_list, keeping only header styling from template."""
        table_pattern = f'<table[^>]*id="{table_id}"[^>]*>'
        table_start_match = re.search(table_pattern, html)
        if not table_start_match:
            return (html, 0)

        table_start = table_start_match.start()
        table_end = html.find('</table>', table_start)
        if table_end < 0:
            return (html, 0)

        table_full = html[table_start:table_end + 8]

        # Find all rows
        rows = list(re.finditer(r'<tr[^>]*>(.*?)</tr>', table_full, re.DOTALL))
        if len(rows) < 2:
            return (html, 0)

        # Keep header row as-is
        header_row_html = rows[0].group(0)

        # Use first data row as template for cell styling
        first_data_row = rows[1].group(1)
        template_cells = list(re.finditer(r'<td[^>]*>(.*?)</td>', first_data_row, re.DOTALL))
        if len(template_cells) < 3:
            return (html, 0)

        # Extract td style templates (opening and closing tags)
        td_templates = []
        for cell in template_cells:
            cell_html = cell.group(0)
            td_match = re.match(r'(<td[^>]*>)(.*?)(</td>)', cell_html, re.DOTALL)
            if td_match:
                td_templates.append((td_match.group(1), td_match.group(3)))

        # Build comparison helper
        def make_comp_text(change):
            if change > 0:
                if arrow_up_src:
                    arrow_img = f'<img src="{arrow_up_src}" style="width: 12px; height: 21px; vertical-align: bottom; border: none; max-height: unset;" />'
                    return f'<span style="color:red">{arrow_img}{change}台</span>'
                return f'<span style="color:red">↑{change}台</span>'
            elif change < 0:
                if arrow_down_src:
                    arrow_img = f'<img src="{arrow_down_src}" style="width: 14px; height: 24px; vertical-align: bottom; border: none; max-height: unset;" />'
                    return f'<span style="color:green">{arrow_img}{abs(change)}台</span>'
                return f'<span style="color:green">↓{abs(change)}台</span>'
            return "--"

        # Helper: get count from a data item (supports both aggregated and raw formats)
        def _get_count(item):
            # If item has 服务器ID计数 field, use it (aggregated format)
            server_id_count = item.get("服务器ID计数")
            if server_id_count is not None and str(server_id_count).strip():
                try:
                    return int(server_id_count)
                except (ValueError, TypeError):
                    pass
            # Otherwise count as 1 (raw host data — each row = one server)
            return 1

        # Helper: normalize owner name (map unassigned to default owner)
        def _normalize_name(raw_name):
            name = str(raw_name or "").strip()
            if not name or name in ("未分配", "未匹配负责人"):
                return "翟召宁"
            return name

        # Build previous week lookup
        prev_lookup = {}
        if prev_data_list:
            for item in prev_data_list:
                name = _normalize_name(item.get("负责人", ""))
                if name in ("合计", "总计"):
                    continue
                prev_lookup[name] = prev_lookup.get(name, 0) + _get_count(item)

        # Build current data lookup
        cur_lookup = {}
        for item in data_list:
            name = _normalize_name(item.get("负责人", ""))
            if name in ("合计", "总计"):
                continue
            cur_lookup[name] = cur_lookup.get(name, 0) + _get_count(item)

        # Collect all names from both current and previous (include dropped-out people)
        all_names = set(cur_lookup.keys()) | set(prev_lookup.keys())

        # Generate data rows for all names, sorted by current count descending
        data_rows_html = []
        total_change = 0
        for name in sorted(all_names, key=lambda n: (-cur_lookup.get(n, 0), n)):
            count = cur_lookup.get(name, 0)
            prev_count = prev_lookup.get(name, 0)
            change = count - prev_count
            total_change += change

            comp_text = make_comp_text(change)
            row_html = f'<tr>{td_templates[0][0]}{name}{td_templates[0][1]}'
            row_html += f'{td_templates[1][0]}{count}{td_templates[1][1]}'
            row_html += f'{td_templates[2][0]}{comp_text}{td_templates[2][1]}</tr>'
            data_rows_html.append(row_html)

        # Generate total row
        total_comp = make_comp_text(total_change)
        total_row_html = f'<tr>{td_templates[0][0]}总计{td_templates[0][1]}'
        total_row_html += f'{td_templates[1][0]}{total}{td_templates[1][1]}'
        total_row_html += f'{td_templates[2][0]}{total_comp}{td_templates[2][1]}</tr>'

        # Rebuild table
        all_rows = [header_row_html] + data_rows_html + [total_row_html]
        new_table_content = "\n".join(all_rows)
        table_attrs = table_full[:table_full.find('>') + 1]
        new_table = f'{table_attrs}<tbody>{new_table_content}</tbody></table>'

        return html[:table_start] + new_table + html[table_end + 8:], total_change

    # Update each table with data and week-over-week comparison
    # tbSted0 = 防护状态中断 (Protection Interrupted)
    # tbSted_agent = Agent缺失 / 未安装Agent (Agent Missing)
    # tbSted1 = 在线未防护 / 未配置配额 (Online Unprotected)
    template, visible_interrupted = update_table_data(template, "tbSted0", protection_interrupted, interrupted_total, prev_protection_interrupted)
    template, visible_missing = update_table_data(template, "tbSted_agent", agent_missing, missing_total, prev_agent_missing)
    template, visible_online = update_table_data(template, "tbSted1", online_unprotected, unquota_total, prev_online_unprotected)

    # Recalculate week_changes from visible table data for summary text consistency
    visible_week_changes = {
        "protection_interrupted": visible_interrupted,
        "agent_missing": visible_missing,
        "online_unprotected": visible_online,
    }

    # Update week-over-week comparison text (now using visible table changes)
    if prev_protection_interrupted is not None or prev_agent_missing is not None or prev_online_unprotected is not None:
        # Section 1: protection interrupted
        interrupted_change = visible_week_changes.get("protection_interrupted", 0)
        if interrupted_change > 0:
            new_text = f"与上周相比较增加<b><span lang=\"EN-US\" style=\"color:red\">{interrupted_change}</span></b>台"
        elif interrupted_change < 0:
            new_text = f"与上周相比较服务器台数减少<b><span lang=\"EN-US\" style=\"color:red\">{abs(interrupted_change)}</span></b>台"
        else:
            new_text = "与上周相比无变化"

        idx1 = template.find('与上周相比较服务器台数减少')
        if idx1 >= 0:
            end_idx = template.find('台', idx1 + 10)
            if end_idx > 0:
                template = template[:idx1] + new_text + template[end_idx + 1:]
        else:
            idx1 = template.find('与上周相比较增加')
            if idx1 >= 0:
                end_idx = template.find('台', idx1 + 10)
                if end_idx > 0:
                    template = template[:idx1] + new_text + template[end_idx + 1:]

        # Section 2: agent missing
        missing_change = visible_week_changes.get("agent_missing", 0)
        if missing_change > 0:
            new_text = f"与上周相比较增加<b><span lang=\"EN-US\" style=\"color:red\">{missing_change}</span></b>台"
        elif missing_change < 0:
            new_text = f"与上周相比较减少<b><span lang=\"EN-US\" style=\"color:red\">{abs(missing_change)}</span></b>台"
        else:
            new_text = "与上周相比无变化"

        idx2 = template.find('刨除暂不安装的剩余')
        if idx2 >= 0:
            compare_idx = template.find('与上周相比较', idx2)
            if compare_idx >= 0:
                end_markers = ['台', '，']
                end_idx = len(template)
                for marker in end_markers:
                    marker_idx = template.find(marker, compare_idx + 10)
                    if marker_idx > 0 and marker_idx < end_idx:
                        end_idx = marker_idx + 1
                template = template[:compare_idx] + new_text + template[end_idx:]

        # Section 3: online unprotected
        unquota_change = visible_week_changes.get("online_unprotected", 0)
        if unquota_change > 0:
            new_text = f"与上周相比增加<b><span lang=\"EN-US\" style=\"color:red\">{unquota_change}</span></b>台"
        elif unquota_change < 0:
            new_text = f"与上周相比减少<b><span lang=\"EN-US\" style=\"color:red\">{abs(unquota_change)}</span></b>台"
        else:
            new_text = "与上周相比无变化"

        all_positions = []
        idx = 0
        while True:
            idx = template.find('与上周相比', idx)
            if idx < 0:
                break
            all_positions.append(idx)
            idx += 10

        if len(all_positions) >= 2:
            compare_idx = all_positions[-1]
            end_idx = len(template)
            for marker in ['台', '，']:
                marker_idx = template.find(marker, compare_idx + 10)
                if marker_idx > 0 and marker_idx < end_idx:
                    end_idx = marker_idx + 1
            template = template[:compare_idx] + new_text + template[end_idx:]

    return template


def send_email(
    to_list: list[str],
    subject: str,
    html_content: str,
    cc_list: list[str] | None = None,
    attachments: list[dict] | None = None,
    smtp_config: dict | None = None,
) -> dict:
    """Send email via SMTP."""
    config = smtp_config or {}
    smtp_host = config.get("smtp_host", SMTP_HOST)
    smtp_port = config.get("smtp_port", SMTP_PORT)
    smtp_user = config.get("smtp_user", SMTP_USER)
    smtp_password = config.get("smtp_password", SMTP_PASSWORD)
    smtp_from = config.get("smtp_from", SMTP_FROM)
    use_tls = config.get("use_tls", SMTP_USE_TLS)

    if not smtp_host:
        return {"success": False, "message": "SMTP服务器未配置"}
    if not to_list:
        return {"success": False, "message": "收件人不能为空"}

    msg = MIMEMultipart()
    msg["From"] = smtp_from or smtp_user
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    if attachments:
        for attachment in attachments:
            file_path = Path(attachment["path"])
            filename = attachment.get("filename", file_path.name)
            if file_path.exists():
                with open(file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename= {filename}")
                    msg.attach(part)

    try:
        all_recipients = to_list + (cc_list or [])
        context = ssl.create_default_context()

        if use_tls:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from or smtp_user, all_recipients, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if use_tls:
                    server.starttls(context=context)
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from or smtp_user, all_recipients, msg.as_string())

        return {"success": True, "message": f"邮件已发送至 {len(all_recipients)} 位收件人"}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP认证失败，请检查用户名和密码"}
    except smtplib.SMTPConnectError:
        return {"success": False, "message": f"无法连接到SMTP服务器 {smtp_host}:{smtp_port}"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"发送邮件失败: {str(e)}"}


def send_daily_report_email(
    to_list: list[str],
    report_date: str,
    report_data: dict,
    cc_list: list[str] | None = None,
    docx_path: str | None = None,
    smtp_config: dict | None = None,
) -> dict:
    """Send daily security report email."""
    try:
        protection_interrupted = report_data.get("protection_interrupted", [])
        agent_missing = report_data.get("agent_missing", [])
        online_unprotected = report_data.get("online_unprotected", [])

        html_content = generate_email_from_report(
            report_date=report_date,
            protection_interrupted=protection_interrupted,
            agent_missing=agent_missing,
            online_unprotected=online_unprotected,
        )

        from datetime import datetime
        try:
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            date_display = f"{dt.month}月{dt.day}日"
        except ValueError:
            date_display = report_date

        subject = f"【主机安全预警】主机安全Agent防护中断&未安装Agent&未已安装Agent未配置配额安全风险预警 - {date_display}"

        attachments = []
        if docx_path:
            docx_file = Path(docx_path)
            if docx_file.exists():
                attachments.append({"filename": f"安全运营日报-{report_date}.docx", "path": str(docx_file)})

        return send_email(
            to_list=to_list,
            subject=subject,
            html_content=html_content,
            cc_list=cc_list,
            attachments=attachments if attachments else None,
            smtp_config=smtp_config,
        )
    except Exception as e:
        return {"success": False, "message": f"发送日报邮件失败: {str(e)}"}


def send_warning_email(
    to_list: list[str],
    report_date: str,
    current_data: dict,
    previous_data: dict | None = None,
    prev_data_files: dict | None = None,
    cc_list: list[str] | None = None,
    smtp_config: dict | None = None,
) -> dict:
    """Send host security warning email with week-over-week comparison."""
    try:
        protection_interrupted = current_data.get("protection_interrupted", [])
        agent_missing = current_data.get("agent_missing", [])
        online_unprotected = current_data.get("online_unprotected", [])

        week_changes = None
        if previous_data:
            # Sum 服务器ID计数 for accurate comparison (consistent with table logic)
            def _sum_server_count(data_list):
                total = 0
                for item in data_list:
                    name = str(item.get("负责人", "") or "").strip()
                    if not name or name in ("未分配", "未匹配负责人"):
                        name = "翟召宁"
                    if name in ("合计", "总计"):
                        continue
                    try:
                        total += int(item.get("服务器ID计数", 1))
                    except (ValueError, TypeError):
                        total += 1
                return total

            current_interrupted = _sum_server_count(protection_interrupted)
            current_missing = _sum_server_count(agent_missing)
            current_unprotected = _sum_server_count(online_unprotected)
            prev_interrupted = previous_data.get("protection_interrupted_count", 0)
            prev_missing = previous_data.get("agent_missing_count", 0)
            prev_unprotected = previous_data.get("online_unprotected_count", 0)
            week_changes = {
                "protection_interrupted": current_interrupted - prev_interrupted,
                "agent_missing": current_missing - prev_missing,
                "online_unprotected": current_unprotected - prev_unprotected,
            }

        # Get previous week's data files for table comparison
        prev_pi = prev_data_files.get("protection_interrupted", []) if prev_data_files else []
        prev_am = prev_data_files.get("agent_missing", []) if prev_data_files else []
        prev_ou = prev_data_files.get("online_unprotected", []) if prev_data_files else []

        html_content = generate_email_from_report(
            report_date=report_date,
            protection_interrupted=protection_interrupted,
            agent_missing=agent_missing,
            online_unprotected=online_unprotected,
            week_changes=week_changes,
            prev_protection_interrupted=prev_pi,
            prev_agent_missing=prev_am,
            prev_online_unprotected=prev_ou,
        )

        from datetime import datetime
        try:
            dt = datetime.strptime(report_date, "%Y-%m-%d")
            date_display = f"{dt.month}月{dt.day}日"
        except ValueError:
            date_display = report_date

        subject = f"【主机安全预警】主机安全Agent防护中断&未安装Agent&未已安装Agent未配置配额安全风险预警 - {date_display}"

        return send_email(
            to_list=to_list,
            subject=subject,
            html_content=html_content,
            cc_list=cc_list,
            smtp_config=smtp_config,
        )
    except Exception as e:
        return {"success": False, "message": f"发送预警邮件失败: {str(e)}"}


def test_smtp_connection(smtp_config: dict) -> dict:
    """Test SMTP connection with provided config."""
    smtp_host = smtp_config.get("smtp_host", "")
    smtp_port = smtp_config.get("smtp_port", 465)
    smtp_user = smtp_config.get("smtp_user", "")
    smtp_password = smtp_config.get("smtp_password", "")
    use_tls = smtp_config.get("use_tls", True)

    if not smtp_host:
        return {"success": False, "message": "SMTP服务器地址不能为空"}

    try:
        context = ssl.create_default_context()
        if use_tls:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=10) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if use_tls:
                    server.starttls(context=context)
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
        return {"success": True, "message": "SMTP连接测试成功"}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP认证失败，请检查用户名和密码"}
    except smtplib.SMTPConnectError:
        return {"success": False, "message": f"无法连接到SMTP服务器 {smtp_host}:{smtp_port}"}
    except Exception as e:
        return {"success": False, "message": f"连接测试失败: {str(e)}"}
