# CTREND (Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA 60(7) 2025) - supplement and main text extraction

Sources read (full text, this session):
- Supplement "Online Appendices", 25 pp. Cambridge static URL (found via the article page link):
  https://static.cambridge.org/content/id/urn%3Acambridge.org%3Aid%3Aarticle%3AS0022109024000747/resource/name/S0022109024000747sup001.pdf
  Saved: tool-results/webfetch-1791735688639-9mriqt.pdf. "S" page numbers below = supplement printed page.
- Main article, JFQA pp. 3116-3153 (open access), saved tool-results/webfetch-1791735707012-jrajrl.pdf. "M" page numbers = journal page (3116..3153).
- The earlier-saved PDFs 2txrsp, 443ljd, l6rlpo, smfho8 are NOT the supplement (Ko&Yang pre-holiday effect; Keller BAA; Keloharju et al. seasonalities; Cieslak et al. FOMC cycle). The other saved PDFs (qqub8d, 8by9jd, l4mcgi, tgyfps, y2xu11, 0k2fhv, 2htigi, onppgi, fm448j) were not opened because the supplement was found directly.
- The old jfqa.org working-paper URL and Cambridge /view/S0022109024000747sup001.pdf both return 404. No SSRN version was found.

Appendix A claim (S p.2): "Except for scaling ... we use only the standard definitions and default settings that can be found in numerous textbooks on technical analysis (Murphy 1999; Ciana 2011)". No software package is named anywhere in the main text or the supplement.

## Indicator parameters (all from supplement Appendix A, S pp.2-6; all inputs are DAILY, CoinMarketCap OHLC + dollar volume)

| Indicator | Definition as printed | Window | S page |
|---|---|---|---|
| helper SMA | (A.1) printed as 1/(L-1) * sum_{l=0}^{L} X_{t-l}, a typo (L+1 terms over L-1) | L | 2 |
| helper EMA | EMA_t = a*P_t + (1-a)*EMA_{t-1}, a = 1/(1+L) (not 2/(L+1)); init with close at t-1 if no EMA_{t-1}. Printed with P_t even for volume/macd inputs | L | 2 |
| rsi | 100 - 100/(1+Gbar/Lbar), Gbar/Lbar = "average gains/losses over the 14-day period". Smoothing not stated; reads as plain 14-day average, not Wilder | 14d | 2-3 |
| stochRSI | (rsi - min rsi)/(max rsi - min rsi) over 14d. Note: text says "previous 14 days" | 14d on rsi | 3 |
| stochK | (P_t - LL)/(HH - LL), LL/HH = lowest low / highest high over 14d. No x100 | 14d | 3 |
| stochD | SMA(stochK, 3) | 3d | 3 |
| cci | X=(P+H+L)/3; (X - SMA(X,20)) / (0.015*AvgDev); AvgDev printed as an un-normalised sum of |X_{t-l}-SMA| over l=0..L-1 (typo, no 1/L; mean absolute deviation intended) | 20d, const 0.015 | 3-4 |
| sma_*d | SMA(P,*)/P_t for * in 3,5,10,20,50,100,200 (list in M p.3123) | 3..200d | 4 |
| macd | (EMA(P,12) - EMA(P,26))/EMA(P,12) (PPO form) | 12/26 | 4 |
| macd_diff_signal | macd - EMA(macd, 9) | 9 | 4 |
| volsma_*d | SMA(V,*)/V_t (V = dollar volume), same 7 lengths | 3..200d | 4 |
| volmacd | (EMA(V,12) - EMA(V,26))/EMA(V,12) | 12/26 | 4-5 |
| volmacd_diff_signal | volmacd - EMA(volmacd, 9) | 9 | 5 |
| chaikin | MONEY FLOW (CMF), not oscillator: AD_t = ((P-L)-(H-P))/(H-L)*V_t (V = dollar volume); chaikin = sum_{21d} AD / sum_{21d} V | 21d | 5 |
| boll_mid | SMA(P,20)/P_t | 20d | 5 |
| boll_low | (SMA20 - 2 sigma)/P_t, sigma = 20d std of closes (ddof unspecified) | 20d, 2 sd | 5 |
| boll_high | (SMA20 + 2 sigma)/P_t | 20d, 2 sd | 6 |
| boll_width | (boll_high - boll_low)/boll_mid | 20d | 6 |

Count check: 5 oscillators + 7 sma + macd + macd_diff_signal (=14) + 7 volsma + volmacd + volmacd_diff + chaikin (=10) + 4 boll = 28. Matches M p.3122 "28 signals".

## Main-text methodology (CS-C-ENet), main article

- Data: CoinMarketCap.com daily OHLC, volume, market cap; needs non-missing close, volume, mcap; drop obs with mcap > Bitcoin's; mcap >= USD 1m; truncate returns at 0.5%/99.5%; sample Apr 2015 - May 2022, 423 weekly obs (M p.3121-3122).
- Indicators are computed on daily data; SMAs are "scaled ... by the cryptocurrencies' closing prices at the end of each week" (M p.3123). So signal is read at week-end from daily indicators. Week-end day and time zone are NOT stated.
- Indicators are converted to cross-sectional ranks mapped to [-0.5, 0.5] before estimation; regressions minimise value-weighted (market-cap) squared residuals (M p.3129).
- Estimation: "fixed rolling window of 52 weeks", parameters then predict the next week (M p.3129). Baseline "In-sample observations 52", "Estimation window rolling" (Table 6, M p.3137).
- Fama-MacBeth smoothing: coefficients averaged over "M periods" (eq 4-5, M p.3127; eq 8, p.3128). M is never given a number in the text. The 52-week rolling window / "in-sample observations 52" is the only stated length, so M=52 is an inference, not a quote.
- Univariate FM regressions per indicator j (eq 7-8), combined by equal weight (eq 9), then pooled elastic-net regression of returns on the J forecasts (eq 10), keep forecasts with theta_j > 0, average them equally (eq 11) (M pp.3127-3129).
- Elastic net: "set the parameter that controls the tradeoff between L1 and L2 regularization to 0.5 and optimize the regularization strength lambda according to the corrected Akaike information criterion (AIC)" (M p.3128 footnote 7). The lambda grid is not given.
- Portfolio: quintile sort on the CTREND signal at the start of each week, value-weighted, rebalanced weekly, long top minus short bottom (M p.3129). Baseline implementation lag 0, breakpoints quintile, validation sample no, forecast weight equal (Table 6, M p.3137). Lag 0 means "data from days up to t-1 are used to predict returns on day t" (M p.3136).
- Returns are "excess returns" (M p.3127, p.3124 regressions) but the risk-free source is never stated.
- Tables 2/3/9 and Appendix: average selected indicators per week = 15 (S p.22). Variable importance top: boll_mid, cci, macd (S p.21-22).
- Headline numbers: H-L 3.87%/wk, t=5.19, Sharpe 1.94, LTW alpha 2.62% (M p.3129-3130). Turnover 68.46%/wk; net of 30/40bp = 2.90% (M p.3147). Sample Apr 2015 - May 2022.

## Output JSON

```json
{
  "indicator": {
    "rsi": {"formula": "100-100/(1+Gbar/Lbar), simple average gains/losses (A.3-A.5); smoothing not stated, not explicitly Wilder", "window": 14, "page": "S p.2-3", "status": "VERIFIED"},
    "stochRSI": {"formula": "(rsi-min rsi)/(max rsi-min rsi), no x100", "window": 14, "page": "S p.3", "status": "VERIFIED"},
    "stochK": {"formula": "(Close-LL14)/(HH14-LL14) using lowest low / highest high, no x100", "window": 14, "page": "S p.3", "status": "VERIFIED"},
    "stochD": {"formula": "SMA(stochK,3)", "window": 3, "page": "S p.3", "status": "VERIFIED"},
    "cci": {"formula": "(TP-SMA20(TP))/(0.015*AvgDev), TP=(C+H+L)/3; AvgDev printed as un-normalised sum (typo)", "window": 20, "constant": 0.015, "page": "S p.3-4", "status": "VERIFIED"},
    "sma_3d,5d,10d,20d,50d,100d,200d": {"formula": "SMA(Close,n)/Close_t", "window": "3,5,10,20,50,100,200", "page": "S p.4; M p.3123", "status": "VERIFIED"},
    "macd": {"formula": "(EMA12(P)-EMA26(P))/EMA12(P)", "window": "12/26", "page": "S p.4", "status": "VERIFIED"},
    "macd_diff_signal": {"formula": "macd-EMA9(macd)", "window": 9, "page": "S p.4", "status": "VERIFIED"},
    "volsma_3d,5d,10d,20d,50d,100d,200d": {"formula": "SMA(dollar volume,n)/Volume_t", "window": "3,5,10,20,50,100,200", "page": "S p.4; M p.3123", "status": "VERIFIED"},
    "volmacd": {"formula": "(EMA12(V)-EMA26(V))/EMA12(V), V=dollar volume", "window": "12/26", "page": "S p.4-5", "status": "VERIFIED"},
    "volmacd_diff_signal": {"formula": "volmacd-EMA9(volmacd)", "window": 9, "page": "S p.5", "status": "VERIFIED"},
    "chaikin": {"formula": "Chaikin MONEY FLOW: sum21(AD)/sum21(V), AD=((C-L)-(H-C))/(H-L)*V, V=dollar volume; not the 3/10 EMA oscillator", "window": 21, "page": "S p.5", "status": "VERIFIED"},
    "boll_mid": {"formula": "SMA20(Close)/Close_t", "window": 20, "page": "S p.5", "status": "VERIFIED"},
    "boll_low": {"formula": "(SMA20-2*sd20)/Close_t", "window": 20, "page": "S p.5", "status": "VERIFIED (std ddof unspecified)"},
    "boll_high": {"formula": "(SMA20+2*sd20)/Close_t", "window": 20, "page": "S p.6", "status": "VERIFIED (std ddof unspecified)"},
    "boll_width": {"formula": "(boll_high-boll_low)/boll_mid", "window": 20, "page": "S p.6", "status": "VERIFIED"},
    "EMA_helper": {"formula": "alpha=1/(1+L); initialised with Close_{t-1}", "window": "L", "page": "S p.2", "status": "VERIFIED (as printed; differs from the usual 2/(L+1))"},
    "SMA_helper": {"formula": "printed 1/(L-1)*sum_{l=0..L}; typo, treat as plain n-day mean", "window": "L", "page": "S p.2", "status": "VERIFIED as printed, typo flagged"}
  },
  "weekly_definition": {"text": "Not defined. Indicators computed on daily data; SMAs scaled by 'closing prices at the end of each week'; weekly rebalance; week-end weekday and time zone not stated; factor data of Liu-Tsyvinski-Wu used for CMKT/CSMB/CMOM", "page": "M p.3123, p.3129", "status": "UNVERIFIED"},
  "fm_window": {"text": "FM coefficients smoothed over M periods (eq 4-5); M not numerically stated. Only length stated: fixed rolling 52 weeks of in-sample data, then next-week forecast; Table 6 baseline 'in-sample observations 52', rolling. M=52 is an inference", "page": "M p.3127, p.3129, p.3137", "status": "52 weeks VERIFIED for rolling window; M=52 UNVERIFIED"},
  "enet": {"text": "alpha (L1/L2 mix) = 0.5; lambda chosen by corrected AIC; lambda grid not given; keep forecasts with theta>0 then equal-weight average; baseline no validation sample, equal forecast weights", "page": "M p.3128 fn7, p.3129, p.3137", "status": "alpha=0.5 and corrected-AIC VERIFIED; grid UNVERIFIED"},
  "risk_free": {"text": "Not stated anywhere; returns just called 'excess returns'", "page": null, "status": "UNVERIFIED"},
  "package": {"text": "None named (no Python/R/Matlab/ta library). Appendix says 'standard definitions and default settings' from Murphy (1999) and Ciana (2011). Figures look Matlab-made but that is not stated", "page": "S p.2", "status": "NOT FOUND"}
}
```

## Still not found
- Week-end day / time zone / exact weekly sampling rule (Sunday-close vs Monday UTC), beyond "end of each week".
- Explicit value of M for FM smoothing (52 is inferred from the 52-week rolling window).
- Elastic-net lambda grid and number of lambdas, standardisation of the forecasts before the pooled ENet, whether theta is constrained.
- Risk-free rate source (none stated).
- Software/package and version.
- RSI average type (simple vs Wilder), std ddof for Bollinger, whether stoch/RSI are scaled 0-100 (stochK/stochRSI as printed are 0-1; irrelevant after cross-sectional ranking).
- Printed typos to resolve by judgement, not by the paper: SMA denominator (L-1), CCI AvgDev missing 1/L, EMA alpha 1/(1+L). Because indicators are rank-transformed cross-sectionally, constant scaling (CCI mean-deviation constant, 0-1 vs 0-100) does not change ranks, but EMA alpha and RSI smoothing do.
- Caveat: these are claims of the paper; this extraction is of definitions only, not evidence of an edge.
