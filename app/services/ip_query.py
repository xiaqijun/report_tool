"""IP 批量查询服务 — 自动区分 IPv4/IPv6，调用不同接口
  IPv4 → lzltool.cn  (POST 签名, 每批 300)
  IPv6 → tooldeer.com (GET 无签名, 每批 500)
"""
import hashlib
import ipaddress
import json
import re
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === lzltool.cn IPv4 常量 ===
CONST1 = '8B45658185274923'
CONST2 = '8A5BF51F1A3A4132'
LZL_BATCH = 300

# === tooldeer IPv6 常量 ===
TOOLDEER_URL = 'https://www.tooldeer.com/api/v1/ipv6'
TOOLDEER_BATCH = 500


def _is_ipv4(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except Exception:
        return False


def _is_ipv6(ip: str) -> bool:
    try:
        ipaddress.IPv6Address(ip)
        return True
    except Exception:
        return False


class _LZLToolAPI:
    """lzltool.cn IPv4 查询封装."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        resp = self.session.get('https://lzltool.cn/tool/ip', verify=False)
        m = re.search(
            r"window\.serverTimeDifference\s*=\s*(\d+)\s*-\s*Math\.round\(Date\.now\(\)\s*/\s*1000\)",
            resp.text,
        )
        self._time_base = int(m.group(1)) if m else 0

    def _ts(self) -> str:
        return str(int(time.time()) + self._time_base - round(time.time()))

    def _sign(self, url: str, data: str, ts: str) -> str:
        sign_input = '|'.join([CONST1, url.strip().lower(), data.strip(), ts, CONST2])
        return hashlib.md5(sign_input.encode()).hexdigest()

    def _query_batch(self, ip_list: list[str]) -> list[dict]:
        url = '/Network/FindIpInfo'
        data = json.dumps({"IpList": ip_list}, separators=(',', ':'))
        ts = self._ts()
        sig = self._sign(url, data, ts)
        resp = self.session.post(
            'https://lzltool.cn' + url,
            data=data,
            headers={
                'RequestSignature': sig,
                'RequestTimestamp': ts,
                'Content-Type': 'application/json',
                'Referer': 'https://lzltool.cn/tool/ip',
                'Origin': 'https://lzltool.cn',
            },
            verify=False,
            timeout=30,
        )
        result = resp.json()
        if result.get('Succeed'):
            return result.get('Data', [])
        raise Exception(f"lzltool 错误: {result.get('Message')}")

    def query(self, ip_list: list[str]) -> list[dict]:
        results = []
        for i in range(0, len(ip_list), LZL_BATCH):
            batch = ip_list[i:i + LZL_BATCH]
            results.extend(self._query_batch(batch))
        return results


def _query_ipv4(ip_list: list[str]) -> list[dict]:
    """查询 IPv4 归属地."""
    if not ip_list:
        return []
    lzl = _LZLToolAPI()
    results = []
    for item in lzl.query(ip_list):
        results.append({
            'Ip': item['Ip'],
            'Country': item.get('Country', ''),
            'Province': item.get('Province', ''),
            'City': item.get('City', ''),
            'Operator': item.get('Operator', ''),
            'Source': 'lzltool',
        })
    return results


def _query_ipv6(ip_list: list[str]) -> list[dict]:
    """查询 IPv6 归属地."""
    if not ip_list:
        return []
    results = []
    for i in range(0, len(ip_list), TOOLDEER_BATCH):
        batch = ip_list[i:i + TOOLDEER_BATCH]
        body = '\n'.join(batch)
        resp = requests.get(
            TOOLDEER_URL,
            params={'wd': body, 'lang': 'cn'},
            timeout=30,
            verify=False,
        )
        data = resp.json()
        if data.get('code') == 200:
            for item in data.get('data', []):
                results.append({
                    'Ip': item['Ip'],
                    'Country': item.get('CountryLong', ''),
                    'Province': item.get('Region', ''),
                    'City': item.get('City', ''),
                    'Operator': '',
                    'Source': 'tooldeer',
                })
        else:
            raise Exception(f"tooldeer 错误: {data.get('msg')}")
    return results


def classify_ips(raw_ips: list[str]) -> dict:
    """对 IP 列表去重并分类。

    Returns:
        {
            'v4': [...], 'v6': [...], 'invalid': [...],
            'total': N, 'unique': N, 'duplicate_count': N,
        }
    """
    ips = list(dict.fromkeys(raw_ips))
    dup_count = len(raw_ips) - len(ips)

    v4 = [ip for ip in ips if _is_ipv4(ip)]
    v6 = [ip for ip in ips if _is_ipv6(ip)]
    invalid = [ip for ip in ips if not _is_ipv4(ip) and not _is_ipv6(ip)]

    return {
        'v4': v4,
        'v6': v6,
        'invalid': invalid,
        'total': len(raw_ips),
        'unique': len(ips),
        'duplicate_count': dup_count,
    }


def query_ips(ip_list: list[str]) -> list[dict]:
    """查询一批 IP 的归属地信息，自动区分 v4/v6。

    Args:
        ip_list: 原始 IP 字符串列表（含空行、无效值等）

    Returns:
        结果列表，每条: {Ip, Country, Province, City, Operator, Source}
    """
    classification = classify_ips(ip_list)

    results = []

    # 查询 IPv4
    if classification['v4']:
        results.extend(_query_ipv4(classification['v4']))

    # 查询 IPv6
    if classification['v6']:
        results.extend(_query_ipv6(classification['v6']))

    # 无效 IP 也记录
    for ip in classification['invalid']:
        results.append({
            'Ip': ip,
            'Country': '(无效IP)',
            'Province': '',
            'City': '',
            'Operator': '',
            'Source': '',
        })

    return results
