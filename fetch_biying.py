#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 · 必盈(BiYing) API 取数器（本地替代东方财富用）
============================================================

背景：用户本机直连东方财富 push2/push2his 的「资金流 / 涨停跌停池」API 被出口 IP
拦截（GitHub CI 干净公网可通），导致本地跑 XXFI 时这些维度降级为 0，与 GitHub 发布值不一致。
必盈 API（api.biyingapi.com）在用户本机直连完全可用，且提供：
  - 全市场涨停股池  hslt/ztgc/{YYYYMMDD}/{licence}   → 涨停家数（官方口径，比自算更权威）
  - 全市场跌停股池  hslt/dtgc/{YYYYMMDD}/{licence}   → 跌停家数
  - （无全市场级资金流；主力/散户净占比必盈只有个股级，无法聚合 → 由 GitHub 回填或降级）

鉴权：licence 作为 URL 路径后缀（非 query 参数）。响应为 gzip 压缩，必须解压。
额度：免费版 200 次/日；本取数器每日仅耗 2 次（涨停+跌停池），余量充足。

关键设计——**GitHub 零改动**：
  BIYING_KEY 仅在「本地」通过环境变量或 biying_key.txt 提供；GitHub Actions 未设置该变量，
  故 CI 运行时此模块函数直接抛 "未配置" 异常，调用方回退到原有东财逻辑（行为完全不变）。
  本地设置了 key，则自动走必盈，彻底摆脱对东财 push2 的依赖。

安全：key 不入库（biying_key.txt 已在 .gitignore）。
"""
import os
import json
import gzip
import ssl
import urllib.request
import datetime

HOST = "https://api.biyingapi.com"
# 本地不入库的 key 读取顺序：环境变量 BIYING_KEY → 同目录 biying_key.txt
BIYING_KEY = os.environ.get("BIYING_KEY") or _read_key_file() if False else os.environ.get("BIYING_KEY")

def _read_key_file():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biying_key.txt")
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read().strip()
        except Exception:
            return None
    return None

# 重新初始化（支持运行时设置环境变量后重新加载）
BIYING_KEY = os.environ.get("BIYING_KEY") or _read_key_file()


def _get(path):
    """GET 必盈 API（licence 已在 path 内），自动解 gzip。返回解析后的 JSON。"""
    if not BIYING_KEY:
        raise RuntimeError("未配置 BIYING_KEY（本地请将 key 写入环境变量或 biying_key.txt）")
    url = f"{HOST}/{path}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def fetch_limit_counts(date_str=None):
    """返回 (limit_up, limit_down, source)。

    date_str: 'YYYY-MM-DD'（必盈股池端点要求的格式）；缺省取今天。
    涨停/跌停为官方股池，len() 即家数。
    """
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    zt = _get(f"hslt/ztgc/{date_str}/{BIYING_KEY}")
    dt = _get(f"hslt/dtgc/{date_str}/{BIYING_KEY}")
    lu = len(zt) if isinstance(zt, list) else 0
    ld = len(dt) if isinstance(dt, list) else 0
    return lu, ld, "biying"


def fetch_published_fund_flow():
    """从 GitHub Pages 抓取最近一次发布报告的 inputs.main_net / inputs.retail_net，
    用于本地对齐「背离」与「散户净流入」两个维度，使本地副表 == GitHub 副表。

    需 Pages 已发布 xxfi_report.json（目前未发布；返回 (None, None) 时调用方优雅降级）。
    这是「本地 vs GitHub 一致性」收口的关键：本地无主力/散户净占比源时，采用云端已算出的真值，
    使本地与 GitHub 完全对齐。要启用，只需把 xxfi_report.json 也提交进 Pages 源目录（一行改动）。
    """
    url = "https://homjanon.github.io/xiaoxu-fear/xxfi_report.json"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            j = json.loads(r.read().decode("utf-8"))
        inp = j.get("inputs") or {}
        return inp.get("main_net"), inp.get("retail_net")
    except Exception:
        return None, None
