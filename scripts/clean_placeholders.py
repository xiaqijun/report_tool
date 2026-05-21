from app.db import get_daily_report_by_date, save_daily_report
import json

def main():
    rd = '2026-05-20'
    r = get_daily_report_by_date(rd)
    if not r:
        print('no report')
        return
    text_fields = [
        'business_stability','trend_comparison','overall_assessment',
        'monitor_start','monitor_end',
        'waf_qps_specs','waf_qps_peak_range','waf_screenshot_path',
        'cfw_bandwidth_spec','cfw_peak_inbound_range','cfw_inbound_peak','cfw_inbound_95th','cfw_screenshot_path',
        'hss_closed_loop_status','hss_screenshot_path',
        'ddos_screenshot_path','secmaster_screenshot_path',
        'emergency_response','emergency_response_screenshot_path',
        'attack_path_assessment','attack_path_screenshot_path',
        'key_work_content','key_work_screenshot_path'
    ]
    changed = False
    for f in text_fields:
        v = r.get(f)
        # treat numeric 0 or string '0' as placeholder
        if v == 0 or v == '0':
            r[f] = ''
            changed = True
    if changed:
        save_daily_report(rd, r, r.get('operator_name','导入者'))
        print('saved changes')
    else:
        print('no changes needed')

    print(json.dumps(get_daily_report_by_date(rd), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
