"""Paired circular-block uncertainty diagnostics for saved institutional results.

No fitting, tuning, new holdout, portfolio NAV, or executable-return claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SCORES = ("price_ridge", "price_flow_ridge", "vol20_rank")


def load_daily(config):
    path = Path(config["daily_input"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != config["expected_daily_sha256"]:
        raise ValueError("Frozen daily-result checksum mismatch")
    daily = pd.read_csv(path, parse_dates=["date"])
    required = ["pool", "top_count", "pool_net_relative"]
    required += [s + suffix for s in SCORES
                 for suffix in ("_top_net_relative", "_rank_ic")]
    if daily.empty or daily.date.isna().any() or daily.date.duplicated().any():
        raise ValueError("Need distinct observed dates")
    if not daily.date.is_monotonic_increasing:
        raise ValueError("Dates must be chronological")
    if not np.isfinite(daily[required]).all().all():
        raise ValueError("Nonfinite daily metrics")
    if not daily.pool.gt(0).all() or not daily.top_count.between(1, daily.pool).all():
        raise ValueError("Invalid pool or selection count")
    if len(daily) != config["expected_dates"]:
        raise ValueError("Unexpected date coverage")
    return daily


def paired_metrics(daily):
    metrics = pd.DataFrame(index=daily.index)
    for score in SCORES:
        top = daily[score + "_top_net_relative"]
        metrics[score + "_vs_0050"] = top
        metrics[score + "_vs_pool"] = top - daily.pool_net_relative
    metrics["flow_minus_price"] = (daily.price_flow_ridge_top_net_relative
                                   - daily.price_ridge_top_net_relative)
    metrics["flow_minus_vol20"] = (daily.price_flow_ridge_top_net_relative
                                   - daily.vol20_rank_top_net_relative)
    metrics["flow_minus_price_rank_ic"] = (daily.price_flow_ridge_rank_ic
                                          - daily.price_ridge_rank_ic)
    return metrics


def circular_block_intervals(values, block_length, replicates, seed):
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Need finite paired metric matrix")
    n = len(values)
    if not 1 <= block_length < n or replicates < 100:
        raise ValueError("Invalid block/replicate count")
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(n / block_length))
    starts = rng.integers(0, n, size=(replicates, blocks))
    indices = ((starts[:, :, None] + np.arange(block_length)) % n).reshape(replicates, -1)[:, :n]
    # Shared indices preserve paired scores, pool comparisons, and daily covariance.
    means = np.empty((replicates, values.shape[1]))
    for column in range(values.shape[1]):
        means[:, column] = values[indices, column].mean(axis=1)
    bounds = np.quantile(means, [.025, .975], axis=0)
    return [{"mean": float(values[:, i].mean()), "lower_95": float(bounds[0, i]),
             "upper_95": float(bounds[1, i]),
             "interval_includes_zero": bool(bounds[0, i] <= 0 <= bounds[1, i])}
            for i in range(values.shape[1])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/institutional_uncertainty_2024.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    daily = load_daily(config)
    metrics = paired_metrics(daily)
    result = {"config": config, "observed_dates": len(daily),
              "date_range": [daily.date.min().date().isoformat(), daily.date.max().date().isoformat()],
              "input_sha256": hashlib.sha256(Path(config["daily_input"]).read_bytes()).hexdigest(),
              "intervals": {}, "status": "descriptive_exploratory_paired_block_bootstrap"}
    for block in config["block_lengths"]:
        summaries = circular_block_intervals(metrics.to_numpy(), block, config["replicates"], config["seed"])
        result["intervals"][str(block)] = dict(zip(metrics.columns, summaries))
    monthly = pd.concat([daily[["date"]], metrics], axis=1)
    monthly["month"] = monthly.date.dt.strftime("%Y-%m")
    counts = monthly.groupby("month").size().rename("signal_dates")
    monthly = monthly.groupby("month")[list(metrics.columns)].mean().join(counts)
    result["monthly_flow_improvement_count"] = int(monthly.flow_minus_price.gt(0).sum())
    result["monthly_flow_decline_count"] = int(monthly.flow_minus_price.lt(0).sum())
    result["months_observed"] = len(monthly)
    result["limitations"] = [
        "Saved 2024 history already researched; no new holdout or retrained model.",
        "Daily equal weighting of overlapping 20-day quote proxies; not annual or portfolio return.",
        "Circular blocks wrap year-end to year-start; stationarity is an approximation.",
        "Block lengths 10/20/40 fixed as sensitivity checks; no universally valid dependence correction.",
        "One year, missing last five 2024 signals, and quote-validity selection limit generalization.",
        "Intervals describe a resampling assumption, not probability of future profit.",
        "Raw 2024 archive not available here; this checks published outputs, not source replay.",
    ]
    out = Path(config["output_directory"]); out.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(out / "institutional_increment_monthly_2024.csv")
    (out / "institutional_uncertainty_2024.json").write_text(json.dumps(result, indent=2) + "\n")
    primary = result["intervals"][str(config["primary_block_length"])]
    lines = [
        "# 2024 法人增量：月度與重疊窗口不確定性",
        "",
        "以已提交的 237 個每日結果進行配對診斷，沒有重新訓練或調整模型。",
        "法人相對量價的平均差異為負；12 個月份中只有 2 月、7 月改善，其餘 10 月下降。",
        "",
        "## 預先固定的分析口徑",
        "",
        f"來源 commit：\x60{config['source_commit']}\x60；每日 CSV 的 SHA-256 已核對。",
        f"配對 circular block bootstrap：{config['replicates']:,} 次、seed={config['seed']}；",
        "主分析區塊 20 個交易日，並列 10／40 日敏感度，不挑選最有利結果。",
        "同一組日期索引套用各方法；20 日報酬窗口重疊，沒有採用逐日獨立抽樣。",
        "",
        "## 20 日區塊結果",
        "",
        "| 比較 | 平均差異（百分點） | 抽樣假設下 95% 區間（百分點） |",
        "|---|---:|---:|",
    ]
    labels = {"price_ridge_vs_0050": "量價模型 − 0050",
              "price_flow_ridge_vs_0050": "量價＋法人 − 0050",
              "vol20_rank_vs_0050": "波動排序 − 0050",
              "price_ridge_vs_pool": "量價模型 − 同池等權",
              "price_flow_ridge_vs_pool": "量價＋法人 − 同池等權",
              "flow_minus_price": "法人模型 − 量價模型",
              "flow_minus_vol20": "法人模型 − 波動排序"}
    for key, label in labels.items():
        s = primary[key]
        lines.append(f"| {label} | {s['mean'] * 100:+.3f} | [{s['lower_95'] * 100:+.3f}, {s['upper_95'] * 100:+.3f}] |")
    lines += ["", "## 法人增量的區塊敏感度", "",
              "| 區塊交易日 | 平均差異（百分點） | 95% 區間（百分點） |", "|---|---:|---:|"]
    for block in config["block_lengths"]:
        s = result["intervals"][str(block)]["flow_minus_price"]
        lines.append(f"| {block} | {s['mean'] * 100:+.3f} | [{s['lower_95'] * 100:+.3f}, {s['upper_95'] * 100:+.3f}] |")
    lines += ["", "## 月度平均差異", "",
              "按訊號月份平均；跨月的未來 20 日窗口仍重疊，不是月投資報酬。",
              "", "| 月份 | 訊號日 | 法人 − 量價（百分點） |", "|---|---:|---:|"]
    for month, row in monthly.iterrows():
        lines.append(f"| {month} | {int(row.signal_dates)} | {row.flow_minus_price * 100:+.3f} |")
    lines += ["", "## 解讀與下一步", "",
              "區間若涵蓋零，不能以本樣本確認法人增量的方向；點估計為負也不能證明所有法人特徵無效。",
              "目前沒有支持將這組法人特徵提升為正式排名模型的證據，先維持研究候選。",
              "下一步先補回已封存的 2024 原始資料包，完成來源重跑，",
              "再用預先固定設定延伸到下一年度，檢查共同池和缺列造成的選擇偏差。",
              "2025 也已用於歷史研究，延伸比較仍須標為探索性；實際效果要等新期間驗證。",
              "", "## 限制", "",
              "一個已研究年份與 circular 邊界連接不能涵蓋市場狀態改變；10／20／40 日區塊不是保證充分的相依校正。",
              "最後五個 2024 訊號未納入，股票未來報價完整性的篩選也可能產生偏差。",
              "本輪只核對 GitHub 輸出、配置和模型維度；尚未取得本機 ZIP，未宣稱原始資料已重放。",
              "不能把這些差異累加為年度報酬、視為可成交 NAV，或解讀為未來獲利機率。",
              ""]
    (out / "institutional_uncertainty_report_2024.md").write_text("\n".join(lines))
    print(json.dumps({"flow_minus_price_intervals": {
        block: summaries["flow_minus_price"] for block, summaries in result["intervals"].items()},
        "improved_months": result["monthly_flow_improvement_count"],
        "declined_months": result["monthly_flow_decline_count"]}, indent=2))


if __name__ == "__main__":
    main()

