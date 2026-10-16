# KAMA descriptive supplement

Added after the rejected KAMA screen; zero new strategy trials and no rule, gate, fill, control or verdict changes. Independent audit checks all716 paths against a separate literal first-maximum oracle. Original716 admissions/715 completed; one LINK cutoff mark. Both populations retained separately.

Original screen `e1216adb2507c79fc4f52a5cb58d14d36e28b5bf`; supplement `c159c20c1b6a5ba17b7ac12c3ba81f9bfba3b56c`; input result `ceba2c1b9f8dfd026f17182e0f8f3e13c35ce7e67b70c571b938cbd4586a2a5c`. Production runtime unchanged.

| Metric | All admissions | Completed only |
|---|---:|---:|
| median_mfe_bps_bounds | [248.42527605257402, 248.42527605257402] | [247.69992922859086, 247.69992922859086] |
| median_mae_bps_bounds | [-220.48619224271647, -220.48619224271647] | [-220.1646090534981, -220.1646090534981] |
| correct_direction_endpoint_fraction | 0.2681564245810056 | 0.26853146853146853 |
| positive_active_week_fraction | 0.35502958579881655 | 0.35502958579881655 |
| positive_calendar_week_fraction_including_zeros | 0.3488372093023256 | 0.3488372093023256 |
| pre_first_mfe_mae_bps_bounds median | [-58.583459254297196, -58.583459254297196] | [-58.687386344851156, -58.687386344851156] |
| hypothetical_peak_net_after_cost_bps_bounds median | [207.51339870306197, 207.51339870306197] | [206.79094747518167, 206.79094747518167] |
| mfe_giveback_to_endpoint_bps_bounds median | [469.6094563442399, 469.6094563442399] | [467.933020054272, 467.933020054272] |

## Return extremes and cost descriptions

```json
{
  "all_admissions": {
    "best_net_trade": {
      "symbol": "SOLUSDT",
      "entry_time": "2023-10-19T08:00:00Z",
      "status": "COMPLETED",
      "net_bps": 6710.058508297739,
      "gross_bps": 6777.032690695725,
      "net_cash_profit_or_cutoff_mark": 7948.982731871754
    },
    "worst_net_trade": {
      "symbol": "LINKUSDT",
      "entry_time": "2025-03-03T00:00:00Z",
      "status": "COMPLETED",
      "net_bps": -1732.3332668761216,
      "gross_bps": -1699.196326061998,
      "net_cash_profit_or_cutoff_mark": -3783.065654426567
    },
    "reference_price_cost_curve": {
      "cases": {
        "10": {
          "n": 716,
          "mean_net_bps": 43.15547364227349,
          "median_net_bps": -128.2474611044515,
          "worst_net_bps": -1707.4929814082618,
          "best_net_bps": 6760.264042329214,
          "per_unit_profit_factor": 1.247551061406948,
          "win_fraction": 0.2639664804469274
        },
        "20": {
          "n": 716,
          "mean_net_bps": 33.117332220271514,
          "median_net_bps": -138.11428516472935,
          "worst_net_bps": -1715.7813483875484,
          "best_net_bps": 6743.512145859172,
          "per_unit_profit_factor": 1.1824315748592087,
          "win_fraction": 0.25837988826815644
        },
        "30": {
          "n": 716,
          "mean_net_bps": 23.089213905030295,
          "median_net_bps": -147.97125717901594,
          "worst_net_bps": -1724.0614394137842,
          "best_net_bps": 6726.776976195388,
          "per_unit_profit_factor": 1.1223101415256418,
          "win_fraction": 0.2569832402234637
        },
        "40": {
          "n": 716,
          "mean_net_bps": 13.07110369190114,
          "median_net_bps": -157.81839189588308,
          "worst_net_bps": -1732.3332668761216,
          "best_net_bps": 6710.058508297739,
          "per_unit_profit_factor": 1.0666761021464446,
          "win_fraction": 0.25139664804469275
        },
        "60": {
          "n": 716,
          "mean_net_bps": -6.935152297028593,
          "median_net_bps": -177.48320828460007,
          "worst_net_bps": -1748.8521805421854,
          "best_net_bps": 6676.67157788997,
          "per_unit_profit_factor": 0.9670853092420518,
          "win_fraction": 0.2430167597765363
        },
        "80": {
          "n": 716,
          "mean_net_bps": -26.901555186380946,
          "median_net_bps": -197.10885173230497,
          "worst_net_bps": -1765.3381880057273,
          "best_net_bps": 6643.351155311696,
          "per_unit_profit_factor": 0.8807233476821851,
          "win_fraction": 0.23324022346368714
        }
      },
      "note": "Conditional reference-return burden on the unchanged baseline admissions, prices and durations. The10/30bps rows are descriptive arithmetic, not new funded simulations, changed admission sets, screening gates or a rescue of the rejected candidate."
    },
    "matched_btc_beta_sensitivity": {
      "btc_net_lower_bps": {
        "n": 716,
        "beta": 1.3071500725606495,
        "intercept_bps": 31.59386094229931,
        "note": "Unweighted paired-event descriptive OLS sensitivity; overlapping durations and sleeves are dependent. Not causal alpha, a tradable hedge, or a statistical confidence interval."
      },
      "btc_net_upper_bps": {
        "n": 716,
        "beta": 1.3071500725606495,
        "intercept_bps": 31.59386094229931,
        "note": "Unweighted paired-event descriptive OLS sensitivity; overlapping durations and sleeves are dependent. Not causal alpha, a tradable hedge, or a statistical confidence interval."
      }
    }
  },
  "completed_only": {
    "best_net_trade": {
      "symbol": "SOLUSDT",
      "entry_time": "2023-10-19T08:00:00Z",
      "status": "COMPLETED",
      "net_bps": 6710.058508297739,
      "gross_bps": 6777.032690695725,
      "net_cash_profit_or_cutoff_mark": 7948.982731871754
    },
    "worst_net_trade": {
      "symbol": "LINKUSDT",
      "entry_time": "2025-03-03T00:00:00Z",
      "status": "COMPLETED",
      "net_bps": -1732.3332668761216,
      "gross_bps": -1699.196326061998,
      "net_cash_profit_or_cutoff_mark": -3783.065654426567
    },
    "reference_price_cost_curve": {
      "cases": {
        "10": {
          "n": 715,
          "mean_net_bps": 43.29274270571924,
          "median_net_bps": -128.30083260354397,
          "worst_net_bps": -1707.4929814082618,
          "best_net_bps": 6760.264042329214,
          "per_unit_profit_factor": 1.248100936907503,
          "win_fraction": 0.26433566433566436
        },
        "20": {
          "n": 715,
          "mean_net_bps": 33.25446408318548,
          "median_net_bps": -138.16760331896828,
          "worst_net_bps": -1715.7813483875484,
          "best_net_bps": 6743.512145859172,
          "per_unit_profit_factor": 1.1830225689167124,
          "win_fraction": 0.25874125874125875
        },
        "30": {
          "n": 715,
          "mean_net_bps": 23.22620870440752,
          "median_net_bps": -148.0245220416654,
          "worst_net_bps": -1724.0614394137842,
          "best_net_bps": 6726.776976195388,
          "per_unit_profit_factor": 1.122932091723941,
          "win_fraction": 0.2573426573426573
        },
        "40": {
          "n": 715,
          "mean_net_bps": 13.207961564531582,
          "median_net_bps": -157.87160352012995,
          "worst_net_bps": -1732.3332668761216,
          "best_net_bps": 6710.058508297739,
          "per_unit_profit_factor": 1.0673207832705913,
          "win_fraction": 0.2517482517482518
        },
        "60": {
          "n": 715,
          "mean_net_bps": -6.798567868340137,
          "median_net_bps": -177.53631359127775,
          "worst_net_bps": -1748.8521805421854,
          "best_net_bps": 6676.67157788997,
          "per_unit_profit_factor": 0.9677562581348333,
          "win_fraction": 0.24335664335664337
        },
        "80": {
          "n": 715,
          "mean_net_bps": -26.76524365692542,
          "median_net_bps": -197.16185093320183,
          "worst_net_bps": -1765.3381880057273,
          "best_net_bps": 6643.351155311696,
          "per_unit_profit_factor": 0.8814021367764647,
          "win_fraction": 0.23356643356643356
        }
      },
      "note": "Conditional reference-return burden on the unchanged baseline admissions, prices and durations. The10/30bps rows are descriptive arithmetic, not new funded simulations, changed admission sets, screening gates or a rescue of the rejected candidate."
    },
    "matched_btc_beta_sensitivity": {
      "btc_net_lower_bps": {
        "n": 715,
        "beta": 1.3071549056524379,
        "intercept_bps": 31.73910073663388,
        "note": "Unweighted paired-event descriptive OLS sensitivity; overlapping durations and sleeves are dependent. Not causal alpha, a tradable hedge, or a statistical confidence interval."
      },
      "btc_net_upper_bps": {
        "n": 715,
        "beta": 1.3071549056524379,
        "intercept_bps": 31.73910073663388,
        "note": "Unweighted paired-event descriptive OLS sensitivity; overlapping durations and sleeves are dependent. Not causal alpha, a tradable hedge, or a statistical confidence interval."
      }
    }
  }
}
```

## Raw BUY completion clocks

```json
{
  "ETHUSDT": {
    "raw_entry_flags": 1756,
    "completion_clock": {
      "n": 1756,
      "utc_hour_counts": {
        "0": 595,
        "8": 591,
        "16": 570
      },
      "nonexclusive_session_counts": {
        "Asia": 1186,
        "London": 591,
        "New_York": 570
      },
      "exclusive_membership_counts": {
        "Asia": 595,
        "Asia+London": 591,
        "New_York": 570
      }
    },
    "session_windows_utc": {
      "Asia": [
        0,
        9
      ],
      "London": [
        7,
        16
      ],
      "New_York": [
        13,
        22
      ]
    },
    "includes_last_available_signal_with_no_next_open": true,
    "note": "Eligible raw BUY flags, including ignored/rejected/final-unexecuted flags; completed-candle availability clock. Fixed UTC point labels, no DST, intrabar-time or session-filter claim."
  },
  "SOLUSDT": {
    "raw_entry_flags": 1781,
    "completion_clock": {
      "n": 1781,
      "utc_hour_counts": {
        "0": 588,
        "8": 601,
        "16": 592
      },
      "nonexclusive_session_counts": {
        "Asia": 1189,
        "London": 601,
        "New_York": 592
      },
      "exclusive_membership_counts": {
        "Asia": 588,
        "Asia+London": 601,
        "New_York": 592
      }
    },
    "session_windows_utc": {
      "Asia": [
        0,
        9
      ],
      "London": [
        7,
        16
      ],
      "New_York": [
        13,
        22
      ]
    },
    "includes_last_available_signal_with_no_next_open": true,
    "note": "Eligible raw BUY flags, including ignored/rejected/final-unexecuted flags; completed-candle availability clock. Fixed UTC point labels, no DST, intrabar-time or session-filter claim."
  },
  "LINKUSDT": {
    "raw_entry_flags": 1744,
    "completion_clock": {
      "n": 1744,
      "utc_hour_counts": {
        "0": 567,
        "8": 592,
        "16": 585
      },
      "nonexclusive_session_counts": {
        "Asia": 1159,
        "London": 592,
        "New_York": 585
      },
      "exclusive_membership_counts": {
        "Asia": 567,
        "Asia+London": 592,
        "New_York": 585
      }
    },
    "session_windows_utc": {
      "Asia": [
        0,
        9
      ],
      "London": [
        7,
        16
      ],
      "New_York": [
        13,
        22
      ]
    },
    "includes_last_available_signal_with_no_next_open": true,
    "note": "Eligible raw BUY flags, including ignored/rejected/final-unexecuted flags; completed-candle availability clock. Fixed UTC point labels, no DST, intrabar-time or session-filter claim."
  }
}
```

## Interpretation and rerun

Full weekly means, cash-PnL concentration by coin/month/week, all/completed summaries and all716 event paths are retained in the lossless supplement; no NAV records are pruned. The original funded ROI is -18.56625152914613% and drawdown -75.0173732008991%. Per-unit trade sums cannot replace portfolio return. First-maximum adverse excursions retain minute OHLC order bounds; retrospective peak moves are not fills. Beta endpoint fits are descriptive sensitivities with overlapping observations, not confidence bounds or causal alpha.10/30bps rows are conditional reference-price arithmetic; original funded20/40/60/80 simulations and original rejection remain authoritative. Fixed UTC sessions are availability point labels, no DST/session filter.

The source snapshot is retained exactly for provenance. To reproduce outside the checkout, restore its base/work/outputs layout, original KAMA result and raw receipts, copy committed public_screen_supplement.py and test_public_screen_supplement.py as the referenced draft snapshots, and copy the retained method/review to outputs. Run the snapshot with production Python3.13.14/NumPy2.2.4/pandas2.2.3/win32 and PYTHONPATH=src. It refuses existing output, changed hashes/runtime/data and multiple joint histories. Current supplement execution commit will reflect the rerun; do not substitute it into the original immutable record. No upstream AGPL source is retained.

The seven failed KAMA gates and no-future-confirmation decision stand. The separately registered Aroon screen may use this descriptive method frozen before its own outcomes.
