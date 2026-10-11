#!/usr/bin/env python3
"""从本仓 git 历史回填 output/bingdian_history.jsonl 与 output/dibudian_history.jsonl。

背景：这两个旁挂指标原本每日覆盖写，历史不可回放。CI 已改为每日追加（见
.github/workflows/xxfi-daily.yml 的 "Append bingdian/dibudian verdict history"），
本脚本只负责把改动之前的存量补齐一次，可重复执行（按日期去重、保留信息更全的那份）。

用法：python backfill_verdict_history.py [--repo .] [--write]
"""
import argparse
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BD_FIELDS = ("down", "down_ratio", "limit_down", "limit_up", "sh_chg",
             "cyb_chg", "etf_down_ratio", "volume_mult")


def blobs(repo, path):
    shas = subprocess.run(["git", "-C", repo, "log", "--format=%H", "--", path],
                          capture_output=True, text=True).stdout.split()
    for sha in shas:
        raw = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"],
                             capture_output=True).stdout.decode("utf-8", "replace")
        try:
            yield json.loads(raw)
        except Exception:
            continue


def bd_row(d):
    dims = d.get("dimensions") or []
    ins = d.get("inputs") or {}
    return {"date": str(d.get("_data_date", ""))[:10],
            "verdict": bool(d.get("verdict")),
            "passed": [x["key"] for x in dims if x.get("pass") is True],
            "missing": [x["key"] for x in dims if x.get("pass") is None],
            "inputs": {k: ins.get(k) for k in BD_FIELDS}}


def dd_row(d):
    return {"date": str(d.get("_data_date", ""))[:10],
            "is_bottom": bool(d.get("is_bottom_today")),
            "ratio": d.get("ratio"),
            "today_total": d.get("today_total"),
            "max90_total": d.get("max90_total")}


def merge(existing, new, weight):
    """同一天保留 weight 更大（信息更全）的一条；已有文件的内容优先保留。"""
    best = {}
    for r in existing:
        best[r["date"]] = r
    for r in new:
        if not r["date"]:
            continue
        cur = best.get(r["date"])
        if cur is None or weight(r) > weight(cur):
            best[r["date"]] = r
    return [best[k] for k in sorted(best)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--write", action="store_true", help="不写盘则只打印统计")
    args = ap.parse_args()

    for path, fn, weight in (
        ("output/bingdian_report.json", bd_row,
         lambda r: 8 - len(r.get("missing") or [])),
        ("output/dibudian_report.json", dd_row,
         lambda r: 1 if isinstance(r.get("ratio"), (int, float)) else 0),
    ):
        out_path = path.replace("report.json", "history.jsonl")
        rows = [fn(d) for d in blobs(args.repo, path) if d.get("_data_date")]
        have = []
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                have = [json.loads(x) for x in f if x.strip()]
        merged = merge(have, rows, weight)
        days = [r["date"] for r in merged]
        ice = [r["date"] for r in merged if r.get("verdict")]
        bot = [r["date"] for r in merged if r.get("is_bottom")]
        print(f"{out_path}: days={len(merged)} range={days[0] if days else '-'}"
              f"~{days[-1] if days else '-'} 冰点={ice} 地量={bot}")
        if args.write:
            with open(out_path, "w", encoding="utf-8") as f:
                for r in merged:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
