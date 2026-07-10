"""
Claude Code usage cost report generator.

Reads every JSONL transcript under ~/.claude/projects/**,
aggregates token usage + notional API list-price cost by (day, model),
and writes a 6-page PDF:
  Page 1 — Daily cost ($) stacked by model + trend
  Page 2 — Daily total tokens stacked by model + trend
  Page 3 — Summary table with per-model totals and trend verdict
  Page 4 — Usage vs efficiency decomposition (msgs/day, cost/msg, tok/msg)
  Page 5 — Cache hit rate over time (confirming cache is not the driver)
  Page 6 — System intelligence + cost efficiency (model mix, output/msg, cost/output)

Run:  uv run python tools/claude_usage_cost_report.py
      python tools/claude_usage_cost_report.py   (if matplotlib is in system env)
"""

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

from claude_pricing import compute_cost, tier, total_tokens

# matplotlib is an OPTIONAL extra (sovereign-imperia-citadel[reports]); it is imported lazily inside main()
# so this module can be imported for its pricing helpers on a pure-stdlib core without it.

MODEL_COLORS = {
    "claude-opus-4-8":            "#4C72B0",
    "claude-opus-4-7":            "#7BA8D9",
    "claude-sonnet-4-6":          "#DD8452",
    "claude-haiku-4-5-20251001":  "#55A868",
    "claude-haiku-4-5":           "#55A868",
}
DEFAULT_COLOR = "#8E8E8E"

MODEL_LABELS = {
    "claude-opus-4-8":            "Opus 4.8",
    "claude-opus-4-7":            "Opus 4.7",
    "claude-sonnet-4-6":          "Sonnet 4.6",
    "claude-haiku-4-5-20251001":  "Haiku 4.5",
    "claude-haiku-4-5":           "Haiku 4.5",
}


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from matplotlib.backends.backend_pdf import PdfPages

    projects_root = Path.home() / ".claude" / "projects"

    print(f"Scanning {projects_root} …", flush=True)

    jsonl_files = sorted(
        glob.glob(str(projects_root / "**" / "*.jsonl"), recursive=True)
    )
    print(f"  Found {len(jsonl_files)} JSONL files", flush=True)

    agg: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "cost": 0.0, "tokens": 0, "messages": 0, "cache_read": 0,
        "output": 0, "input_fresh": 0,
    })
    seen_ids: set[str] = set()
    rows_parsed = 0
    rows_skipped_dup = 0
    rows_skipped_synthetic = 0

    for path in jsonl_files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if obj.get("type") != "assistant":
                        continue

                    msg = obj.get("message")
                    if not isinstance(msg, dict):
                        continue

                    usage = msg.get("usage")
                    if not usage:
                        continue

                    model = msg.get("model", "")
                    if tier(model) is None:
                        rows_skipped_synthetic += 1
                        continue

                    msg_id = msg.get("id", "")
                    if msg_id and msg_id in seen_ids:
                        rows_skipped_dup += 1
                        continue
                    if msg_id:
                        seen_ids.add(msg_id)

                    day = (obj.get("timestamp") or "")[:10]
                    if not day:
                        continue

                    cost  = compute_cost(usage, model)
                    toks  = total_tokens(usage)

                    key = (day, model)
                    agg[key]["cost"]        += cost
                    agg[key]["tokens"]      += toks
                    agg[key]["messages"]    += 1
                    agg[key]["cache_read"]  += usage.get("cache_read_input_tokens", 0) or 0
                    agg[key]["output"]      += usage.get("output_tokens", 0) or 0
                    agg[key]["input_fresh"] += usage.get("input_tokens", 0) or 0
                    rows_parsed += 1

        except (OSError, PermissionError):
            pass

    print(f"  Parsed {rows_parsed} rows  |  skipped {rows_skipped_dup} duplicates"
          f"  |  {rows_skipped_synthetic} synthetic", flush=True)

    if rows_parsed == 0:
        sys.exit("No assistant usage rows found — nothing to chart.")

    all_days   = sorted({k[0] for k in agg})
    all_models = sorted({k[1] for k in agg})

    print(f"  Date range: {all_days[0]} → {all_days[-1]} ({len(all_days)} active days)", flush=True)
    print(f"  Models: {all_models}", flush=True)

    cost_by_day  = [sum(agg[(d, m)]["cost"]   for m in all_models) for d in all_days]
    tok_by_day   = [sum(agg[(d, m)]["tokens"] for m in all_models) for d in all_days]

    cost_matrix  = {m: [agg[(d, m)]["cost"]   for d in all_days] for m in all_models}
    tok_matrix   = {m: [agg[(d, m)]["tokens"] for d in all_days] for m in all_models}

    x = list(range(len(all_days)))
    x_labels = all_days


    def linreg(y_vals):
        n = len(y_vals)
        if n < 2:
            return 0.0, y_vals[0] if y_vals else 0.0
        sx  = sum(range(n))
        sy  = sum(y_vals)
        sxy = sum(i * v for i, v in enumerate(y_vals))
        sxx = sum(i * i for i in range(n))
        denom = n * sxx - sx * sx
        if denom == 0:
            return 0.0, sy / n
        slope     = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        return slope, intercept


    cost_slope, cost_intercept = linreg(cost_by_day)
    tok_slope,  tok_intercept  = linreg(tok_by_day)

    trend_cost = [cost_intercept + cost_slope * i for i in x]
    trend_tok  = [tok_intercept  + tok_slope  * i for i in x]

    grand_cost   = sum(cost_by_day)
    grand_tokens = sum(tok_by_day)
    per_model_cost   = {m: sum(cost_matrix[m])   for m in all_models}
    per_model_tokens = {m: sum(tok_matrix[m])    for m in all_models}

    msgs_by_day      = [sum(agg[(d, m)]["messages"]   for m in all_models) for d in all_days]
    cache_read_by_day= [sum(agg[(d, m)]["cache_read"] for m in all_models) for d in all_days]
    cost_per_msg     = [cost_by_day[i] / max(msgs_by_day[i], 1) for i in range(len(all_days))]
    tok_per_msg      = [tok_by_day[i]  / max(msgs_by_day[i], 1) for i in range(len(all_days))]
    cache_hit_pct    = [100 * cache_read_by_day[i] / max(tok_by_day[i], 1) for i in range(len(all_days))]

    msgs_slope,    msgs_intercept    = linreg(msgs_by_day)
    cpm_slope,     cpm_intercept     = linreg(cost_per_msg)
    tpm_slope,     tpm_intercept     = linreg(tok_per_msg)
    cache_slope,   cache_intercept   = linreg(cache_hit_pct)

    trend_msgs  = [msgs_intercept  + msgs_slope  * i for i in x]
    trend_cpm   = [cpm_intercept   + cpm_slope   * i for i in x]
    trend_tpm   = [tpm_intercept   + tpm_slope   * i for i in x]
    trend_cache = [cache_intercept + cache_slope * i for i in x]

    TIER_MODELS = {
        "opus":   [m for m in all_models if "opus"   in m.lower()],
        "sonnet": [m for m in all_models if "sonnet" in m.lower()],
        "haiku":  [m for m in all_models if "haiku"  in m.lower()],
    }
    TIER_COLORS = {"opus": "#4C72B0", "sonnet": "#DD8452", "haiku": "#55A868"}


    def day_tier_msgs(d, t):
        return sum(agg[(d, m)]["messages"] for m in TIER_MODELS[t])


    def day_tier_cost(d, t):
        return sum(agg[(d, m)]["cost"] for m in TIER_MODELS[t])


    tier_msg_pct = {
        t: [100 * day_tier_msgs(d, t) / max(msgs_by_day[i], 1)
            for i, d in enumerate(all_days)]
        for t in ["opus", "sonnet", "haiku"]
    }

    output_by_day = [sum(agg[(d, m)]["output"] for m in all_models) for d in all_days]
    out_per_msg   = [output_by_day[i] / max(msgs_by_day[i], 1) for i in range(len(all_days))]

    cost_per_1k_out = [
        cost_by_day[i] / (output_by_day[i] / 1000) if output_by_day[i] else 0
        for i in range(len(all_days))
    ]

    opm_slope,   opm_intercept  = linreg(out_per_msg)
    c1k_slope,   c1k_intercept  = linreg(cost_per_1k_out)
    sonnet_slope, sonnet_intercept = linreg(tier_msg_pct["sonnet"])

    trend_opm  = [opm_intercept + opm_slope  * i for i in x]
    trend_c1k  = [c1k_intercept + c1k_slope  * i for i in x]
    trend_son  = [sonnet_intercept + sonnet_slope * i for i in x]

    BAR_WIDTH = 0.7
    FIGSIZE   = (14, 7)

    plt.rcParams.update({
        "font.family":    "DejaVu Sans",
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        "axes.grid":          True,
        "grid.linestyle":     "--",
        "grid.alpha":         0.4,
        "axes.labelsize":     11,
        "xtick.labelsize":    9,
        "ytick.labelsize":    9,
    })


    def model_color(m):
        return MODEL_COLORS.get(m, DEFAULT_COLOR)


    def model_label(m):
        return MODEL_LABELS.get(m, m)


    out_path = Path(__file__).parent.parent / "claude-usage-cost-report.pdf"

    with PdfPages(str(out_path)) as pdf:

        fig, ax = plt.subplots(figsize=FIGSIZE)

        bottoms = [0.0] * len(all_days)
        legend_patches = []
        for m in all_models:
            vals = cost_matrix[m]
            ax.bar(x, vals, width=BAR_WIDTH, bottom=bottoms,
                   color=model_color(m), label=model_label(m), zorder=2)
            bottoms = [b + v for b, v in zip(bottoms, vals, strict=False)]
            legend_patches.append(
                mpatches.Patch(color=model_color(m), label=model_label(m))
            )

        ax.plot(x, cost_by_day, color="black", linewidth=1.4,
                marker="o", markersize=4, label="Total", zorder=3)

        direction = "↓" if cost_slope <= 0 else "↑"
        ax.plot(x, trend_cost, color="crimson", linewidth=1.5,
                linestyle="--", zorder=3,
                label=f"Trend {direction} ${abs(cost_slope):.2f}/day")

        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Notional cost (USD)")
        ax.set_title("Daily Claude API cost by model", fontsize=14, fontweight="bold", pad=12)

        verdict_str = (
            f"Trend: {'FALLING' if cost_slope <= 0 else 'RISING'} "
            f"~${abs(cost_slope):.3f}/day over {len(all_days)} active days"
        )
        ax.set_xlabel(verdict_str, labelpad=8, fontsize=10, color="crimson")

        legend_patches += [
            plt.Line2D([0], [0], color="black", linewidth=1.4, marker="o",
                       markersize=4, label="Total"),
            plt.Line2D([0], [0], color="crimson", linewidth=1.5,
                       linestyle="--", label=f"Trend {direction} ${abs(cost_slope):.2f}/day"),
        ]
        ax.legend(handles=legend_patches, loc="upper left", fontsize=8, framealpha=0.7)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.2f"))

        note = ("Note: notional list-price cost. Actual billing under subscription/Max plan differs.\n"
                "Dollar figures are a consistent proxy for 'how much work the system is doing.'")
        fig.text(0.5, 0.01, note, ha="center", fontsize=7.5, color="#555555",
                 style="italic", wrap=True)

        fig.tight_layout(rect=[0, 0.04, 1, 1])
        pdf.savefig(fig, dpi=150)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=FIGSIZE)

        bottoms = [0] * len(all_days)
        legend_patches = []
        for m in all_models:
            vals = tok_matrix[m]
            ax.bar(x, vals, width=BAR_WIDTH, bottom=bottoms,
                   color=model_color(m), label=model_label(m), zorder=2)
            bottoms = [b + v for b, v in zip(bottoms, vals, strict=False)]
            legend_patches.append(
                mpatches.Patch(color=model_color(m), label=model_label(m))
            )

        ax.plot(x, tok_by_day, color="black", linewidth=1.4,
                marker="o", markersize=4, label="Total", zorder=3)

        tok_dir = "↓" if tok_slope <= 0 else "↑"
        ax.plot(x, trend_tok, color="darkorange", linewidth=1.5,
                linestyle="--", zorder=3,
                label=f"Trend {tok_dir} {abs(tok_slope):,.0f} tok/day")

        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Tokens (all types)")
        ax.set_title("Daily token consumption by model", fontsize=14, fontweight="bold", pad=12)

        tok_verdict = (
            f"Trend: {'FALLING' if tok_slope <= 0 else 'RISING'} "
            f"~{abs(tok_slope):,.0f} tokens/day over {len(all_days)} active days"
        )
        ax.set_xlabel(tok_verdict, labelpad=8, fontsize=10, color="darkorange")

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K"
        ))

        legend_patches += [
            plt.Line2D([0], [0], color="black", linewidth=1.4, marker="o",
                       markersize=4, label="Total"),
            plt.Line2D([0], [0], color="darkorange", linewidth=1.5,
                       linestyle="--", label=f"Trend {tok_dir} {abs(tok_slope):,.0f} tok/day"),
        ]
        ax.legend(handles=legend_patches, loc="upper left", fontsize=8, framealpha=0.7)

        note2 = ("Tokens = input + output + cache_creation + cache_read for every assistant message.\n"
                 "Cache tokens are weighted in cost, but counted equally here to show raw system load.")
        fig.text(0.5, 0.01, note2, ha="center", fontsize=7.5, color="#555555",
                 style="italic", wrap=True)

        fig.tight_layout(rect=[0, 0.04, 1, 1])
        pdf.savefig(fig, dpi=150)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=FIGSIZE)
        ax.axis("off")

        avg_cost_per_day = grand_cost / len(all_days)
        grand_tokens / len(all_days)

        fig.text(0.5, 0.93, "Usage report — summary", ha="center",
                 fontsize=16, fontweight="bold")
        fig.text(0.5, 0.88,
                 f"Period: {all_days[0]} → {all_days[-1]}  |  "
                 f"{len(all_days)} active days  |  {rows_parsed:,} messages",
                 ha="center", fontsize=11, color="#333333")

        fig.text(0.5, 0.82,
                 f"Total notional cost:  ${grand_cost:,.4f}    "
                 f"Total tokens: {grand_tokens/1e6:.2f}M    "
                 f"Avg cost/day: ${avg_cost_per_day:.4f}",
                 ha="center", fontsize=12, color="#1a1a1a",
                 bbox={"boxstyle": "round,pad=0.4", "fc": "#F0F0F0", "ec": "#BBBBBB"})

        headers = ["Model", "Notional cost ($)", "% of total cost",
                    "Tokens (M)", "% of total tokens", "Messages"]
        table_data = []
        for m in sorted(all_models, key=lambda mm: per_model_cost[mm], reverse=True):
            cost_pct = 100 * per_model_cost[m] / grand_cost if grand_cost > 0 else 0
            tok_pct  = 100 * per_model_tokens[m] / grand_tokens if grand_tokens > 0 else 0
            msgs     = sum(agg[(d, m)]["messages"] for d in all_days)
            table_data.append([
                model_label(m),
                f"${per_model_cost[m]:,.4f}",
                f"{cost_pct:.1f}%",
                f"{per_model_tokens[m]/1e6:.2f}",
                f"{tok_pct:.1f}%",
                f"{msgs:,}",
            ])

        tbl = ax.table(
            cellText=table_data,
            colLabels=headers,
            cellLoc="center",
            loc="center",
            bbox=[0.02, 0.25, 0.96, 0.45],
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        for (row, _col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor("#3A3A5C")
                cell.set_text_props(color="white", fontweight="bold")
            elif row % 2 == 0:
                cell.set_facecolor("#F5F5F5")
            cell.set_edgecolor("#CCCCCC")

        cost_verdict_line = (
            f"[$] Cost trend:   {'▼ FALLING' if cost_slope <= 0 else '▲ RISING'}"
            f"  ~${abs(cost_slope):.4f}/active-day"
        )
        tok_verdict_line = (
            f"[T] Token trend:  {'▼ FALLING' if tok_slope <= 0 else '▲ RISING'}"
            f"  ~{abs(tok_slope):,.0f} tokens/active-day"
        )
        fig.text(0.5, 0.19, cost_verdict_line, ha="center", fontsize=12,
                 color="#007700" if cost_slope <= 0 else "#CC0000", fontweight="bold")
        fig.text(0.5, 0.14, tok_verdict_line,  ha="center", fontsize=12,
                 color="#007700" if tok_slope  <= 0 else "#CC0000", fontweight="bold")

        overall_color = "#007700" if (cost_slope <= 0 or tok_slope <= 0) else "#CC0000"
        if cost_slope <= 0 and tok_slope <= 0:
            answer = "[OK]  Both cost AND tokens are trending DOWN — the system is getting more efficient."
        elif cost_slope <= 0:
            answer = "[OK]  Cost is trending DOWN even if raw token count is up (better cache hit rate?)."
        elif tok_slope <= 0:
            answer = "[OK]  Token consumption is trending DOWN even if cost is slightly up (model mix?)."
        else:
            answer = "[!!]  Both cost and tokens are trending UP over this window."

        fig.text(0.5, 0.07, answer, ha="center", fontsize=11,
                 color=overall_color, fontweight="bold",
                 bbox={"boxstyle": "round,pad=0.4", "fc": "#FAFAFA", "ec": overall_color})

        fig.text(0.5, 0.02,
                 "Notional list-price cost (not actual billing). Covers every Claude Code "
                 "project transcript found on this machine.",
                 ha="center", fontsize=8, color="#777777", style="italic")

        fig.tight_layout()
        pdf.savefig(fig, dpi=150)
        plt.close(fig)

        fig, axes = plt.subplots(1, 3, figsize=(17, 6))
        fig.suptitle("Why is cost falling?  Usage vs Efficiency decomposition",
                     fontsize=14, fontweight="bold", y=1.01)

        PHASE_X = 4.5

        ax = axes[0]
        ax.bar(x, msgs_by_day, width=BAR_WIDTH, color="#5B9BD5", zorder=2, alpha=0.85)
        ax.plot(x, trend_msgs, color="crimson", linewidth=2, linestyle="--", zorder=3)
        ax.axvline(PHASE_X, color="#888", linewidth=1.2, linestyle=":", zorder=1)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Messages per active day")
        msgs_dir = "FALLING" if msgs_slope < 0 else "FLAT / RISING"
        msgs_col = "#777777" if abs(msgs_slope) < 5 else ("#007700" if msgs_slope < 0 else "#CC0000")
        ax.set_title(f"Messages/day\n({msgs_dir} {msgs_slope:+.1f}/day)", fontsize=11,
                     color=msgs_col, fontweight="bold")
        ax.text(PHASE_X + 0.15, max(msgs_by_day) * 0.95, "work\nshifts",
                fontsize=7.5, color="#888", va="top")

        ax = axes[1]
        ax.plot(x, cost_per_msg, color="#DD8452", linewidth=2, marker="o", markersize=5, zorder=3)
        ax.plot(x, trend_cpm,    color="crimson",  linewidth=2, linestyle="--", zorder=3)
        ax.axvline(PHASE_X, color="#888", linewidth=1.2, linestyle=":", zorder=1)
        ax.fill_between(x, cost_per_msg, alpha=0.12, color="#DD8452")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Cost per message (USD)")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.3f"))
        cpm_dir = "FALLING" if cpm_slope < 0 else "RISING"
        cpm_col = "#007700" if cpm_slope < 0 else "#CC0000"
        ax.set_title(f"Cost per message\n({'▼ ' if cpm_slope < 0 else '▲ '}{cpm_dir}  ${cpm_slope:+.5f}/msg/day)",
                     fontsize=11, color=cpm_col, fontweight="bold")

        ax = axes[2]
        ax.plot(x, tok_per_msg, color="#4C72B0", linewidth=2, marker="o", markersize=5, zorder=3)
        ax.plot(x, trend_tpm,   color="crimson",  linewidth=2, linestyle="--", zorder=3)
        ax.axvline(PHASE_X, color="#888", linewidth=1.2, linestyle=":", zorder=1)
        ax.fill_between(x, tok_per_msg, alpha=0.12, color="#4C72B0")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Tokens per message")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{v/1e3:.0f}K" if v < 1e6 else f"{v/1e6:.1f}M"
        ))
        tpm_dir = "FALLING" if tpm_slope < 0 else "RISING"
        tpm_col = "#007700" if tpm_slope < 0 else "#CC0000"
        ax.set_title(f"Tokens per message\n({'▼ ' if tpm_slope < 0 else '▲ '}{tpm_dir}  {tpm_slope:+,.0f} tok/msg/day)",
                     fontsize=11, color=tpm_col, fontweight="bold")

        verdict_text = (
            "Volume is FLAT — you use the system just as much as before.\n"
            "Cost fell because each task got cheaper (fewer tokens/msg).  "
            "The dotted line marks when infrastructure work completed."
        )
        fig.text(0.5, -0.04, verdict_text, ha="center", fontsize=9.5,
                 color="#333333", style="italic",
                 bbox={"boxstyle": "round,pad=0.4", "fc": "#F8F8F0", "ec": "#AAAAAA"})

        fig.tight_layout(rect=[0, 0.01, 1, 1])
        pdf.savefig(fig, dpi=150, bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=FIGSIZE)

        bar_colors = ["#55A868" if v >= 90 else "#DD8452" for v in cache_hit_pct]
        ax.bar(x, cache_hit_pct, width=BAR_WIDTH, color=bar_colors, zorder=2, alpha=0.8)
        ax.plot(x, trend_cache, color="crimson", linewidth=2, linestyle="--", zorder=3,
                label=f"Trend  {cache_slope:+.2f} pp/day")
        ax.axhline(90, color="#4C72B0", linewidth=1, linestyle=":", zorder=1,
                   label="90% reference line")

        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Cache-read tokens as % of all tokens")
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))

        cache_dir   = "falling" if cache_slope < 0 else "rising"
        cache_color = "#CC0000" if cache_slope < 0 else "#007700"
        ax.set_title(
            "Cache hit rate — is it RISING (making system cheaper)?",
            fontsize=14, fontweight="bold", pad=12
        )
        verdict_cache = (
            f"Cache hit rate is {cache_dir.upper()} ({cache_slope:+.2f} pp/day) — "
            f"cache efficiency is NOT the driver of falling costs."
        )
        ax.set_xlabel(verdict_cache, labelpad=8, fontsize=10, color=cache_color)
        ax.legend(fontsize=9, loc="lower left", framealpha=0.7)

        note5 = ("Cache-read % = cache_read_tokens / (input + output + cache_creation + cache_read).\n"
                 "A rising cache hit rate would mean the system is reusing more cached context — "
                 "which would reduce cost. This chart shows that is NOT what is happening.")
        fig.text(0.5, 0.01, note5, ha="center", fontsize=7.5, color="#555555",
                 style="italic", wrap=True)

        fig.tight_layout(rect=[0, 0.05, 1, 1])
        pdf.savefig(fig, dpi=150)
        plt.close(fig)

        fig, axes = plt.subplots(1, 3, figsize=(17, 6))
        fig.suptitle("Is the system smarter and more cost-efficient?",
                     fontsize=14, fontweight="bold", y=1.01)

        ax = axes[0]
        bottoms = [0.0] * len(all_days)
        for t in ["haiku", "sonnet", "opus"]:
            vals = tier_msg_pct[t]
            ax.bar(x, vals, width=BAR_WIDTH, bottom=bottoms,
                   color=TIER_COLORS[t], label=t.capitalize(), zorder=2, alpha=0.85)
            bottoms = [b + v for b, v in zip(bottoms, vals, strict=False)]
        ax.plot(x, trend_son, color="white", linewidth=2, linestyle="--", zorder=3,
                label=f"Sonnet% trend {sonnet_slope:+.1f}pp/day")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("% of messages")
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        son_dir = "RISING" if sonnet_slope >= 0 else "FALLING"
        son_col = "#007700" if sonnet_slope >= 0 else "#CC0000"
        ax.set_title(f"Model mix over time\n(Sonnet % {son_dir} {sonnet_slope:+.1f}pp/day)",
                     fontsize=11, color=son_col, fontweight="bold")
        ax.legend(fontsize=8, loc="upper left", framealpha=0.6)
        ax.text(0.5, -0.22,
                "Smarter routing = using cheaper Sonnet\nfor tasks that don't need Opus",
                ha="center", transform=ax.transAxes, fontsize=8.5, color="#444444",
                style="italic")

        ax = axes[1]
        ax.bar(x, out_per_msg, width=BAR_WIDTH, color="#7B68EE", alpha=0.8, zorder=2)
        ax.plot(x, trend_opm, color="crimson", linewidth=2, linestyle="--", zorder=3,
                label=f"Trend {opm_slope:+.0f} tok/msg/day")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Output tokens per message")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{v/1e3:.0f}K" if v >= 1000 else f"{v:.0f}"
        ))
        opm_dir = "FALLING" if opm_slope < 0 else "STABLE / RISING"
        opm_col = "#CC6600" if opm_slope < -50 else "#007700"
        ax.set_title(f"Output (useful work) per task\n({opm_dir}  {opm_slope:+.0f} tok/msg/day)",
                     fontsize=11, color=opm_col, fontweight="bold")
        ax.legend(fontsize=8, loc="upper right", framealpha=0.6)
        ax.text(0.5, -0.22,
                "Output tokens = what Claude actually generated.\n"
                "Stable/rising = same useful work per task despite lower total cost.",
                ha="center", transform=ax.transAxes, fontsize=8.5, color="#444444",
                style="italic")

        ax = axes[2]
        ax.plot(x, cost_per_1k_out, color="#E377C2", linewidth=2,
                marker="o", markersize=5, zorder=3)
        ax.plot(x, trend_c1k, color="crimson", linewidth=2, linestyle="--", zorder=3,
                label=f"Trend ${c1k_slope:+.4f}/day")
        ax.fill_between(x, cost_per_1k_out, alpha=0.12, color="#E377C2")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_ylabel("Cost per 1K output tokens (USD)")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.3f"))
        c1k_dir = "FALLING" if c1k_slope < 0 else "RISING"
        c1k_col = "#007700" if c1k_slope < 0 else "#CC0000"
        c1k_arrow = "▼ " if c1k_slope < 0 else "▲ "
        ax.set_title(f"Cost per unit of useful work\n({c1k_arrow}{c1k_dir}  ${c1k_slope:+.5f}/day)",
                     fontsize=11, color=c1k_col, fontweight="bold")
        ax.legend(fontsize=8, loc="upper right", framealpha=0.6)
        ax.text(0.5, -0.22,
                "Cost per 1K output tokens = what you pay\nper unit of actual AI work done.",
                ha="center", transform=ax.transAxes, fontsize=8.5, color="#444444",
                style="italic")

        is_smarter = sonnet_slope >= 0 or opm_slope >= -100
        is_cheaper  = c1k_slope < 0
        if is_smarter and is_cheaper:
            verdict6 = ("[YES]  The system IS smarter (better model routing) AND more cost-efficient "
                        "(lower cost per output token).")
            v6col = "#007700"
        elif is_cheaper:
            verdict6 = "[PARTLY]  Cost per output token is falling but model routing has not fully shifted."
            v6col = "#CC6600"
        else:
            verdict6 = "[NO]  Cost per output token is not yet falling — routing or model mix needs review."
            v6col = "#CC0000"

        fig.text(0.5, -0.04, verdict6, ha="center", fontsize=10,
                 color=v6col, fontweight="bold",
                 bbox={"boxstyle": "round,pad=0.4", "fc": "#F8F8F0", "ec": v6col})

        fig.tight_layout(rect=[0, 0.04, 1, 1])
        pdf.savefig(fig, dpi=150, bbox_inches="tight")
        plt.close(fig)

        d = pdf.infodict()
        d["Title"]   = "Claude Code usage cost report"
        d["Author"]  = "claude_usage_cost_report.py"
        d["Subject"] = f"Token/cost trend {all_days[0]} → {all_days[-1]}"

    print()
    print("=" * 60)
    print(f"  PDF written → {out_path.resolve()}")
    print("=" * 60)
    print(f"  Period        : {all_days[0]} → {all_days[-1]}  ({len(all_days)} active days)")
    print(f"  Messages      : {rows_parsed:,}")
    print(f"  Models        : {len(all_models)}")
    print(f"  Grand cost    : ${grand_cost:,.4f}  (notional list price)")
    print(f"  Grand tokens  : {grand_tokens/1e6:.2f}M")
    print(f"  Avg cost/day  : ${avg_cost_per_day:.4f}")
    print()
    print(f"  Cost trend    : {'↓ FALLING' if cost_slope <= 0 else '↑ RISING'}"
          f"  ~${abs(cost_slope):.4f}/active-day")
    print(f"  Token trend   : {'↓ FALLING' if tok_slope <= 0 else '↑ RISING'}"
          f"  ~{abs(tok_slope):,.0f} tokens/active-day")
    print()
    print("Per-model breakdown:")
    for m in sorted(all_models, key=lambda mm: per_model_cost[mm], reverse=True):
        msgs = sum(agg[(d, m)]["messages"] for d in all_days)
        print(f"  {model_label(m):20s}  ${per_model_cost[m]:9.4f}  "
              f"{per_model_tokens[m]/1e6:6.2f}M tok  {msgs:5,} msgs")
    print("=" * 60)


if __name__ == "__main__":
    main()
