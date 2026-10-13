# TPEx prospective preflight, 2026-10-13 15:09 Asia/Taipei

Status: source probe only; no prospective signal or performance evaluation.

- Authorized five-file sync on main: 89a19e1ea44ebc21646936ecb8e579708c0ba41e.
- All eight frozen source/config Git blobs in configs/tpex_prospective_protocol.json match the restored local copy.
- 24 relevant unit tests passed.
- TPEx 2026-10-12 daily quote source (https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=2026/10/12&type=EW&response=json): observed 2026-10-13 15:08:58 +08:00, SHA-256 b1b91e825838dbed168e7610a4e2bf09f1c2b8629171648007b799f40f19929e. 1,012 rows, 990 complete prices, no duplicate codes or OHLC errors; 22 missing prices remain unknown.
- TPEx 2026-08 domestic static revenue (https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_115_8_0.html): observed 2026-10-13 15:09:21 +08:00, SHA-256 808b1f29a34de8c3b53500576d51aa81cbdd5d10be3e83b0fe7442e876f4cb77; 863 unique rows, export date 115/10/13. An earlier read-only probe produced a different SHA-256 4d41d7babdf9f4948ab9b7ad5a356ca6a6450138faad5e4fc2dd3ba8c716394b but its bytes were not retained; two later reads match the saved 808b bytes. Reason for difference unknown. Export date is not the first company disclosure time.
- Two source bodies and observation records archived as tpex_prospective_source_probe_20261013.zip; ZIP SHA-256 c0b6d93f8aa155321928031d75c76637836b5c06028f57c1bfd8eca805d9d7c1, Library ID libfile_4dd61ce503d88191acb2cfb741fc11b4. Downloaded copy matched; four payload files passed SHA-256 and ZIP CRC.

Activation gate remains closed. This validates two historic responses, not a complete current-day quote, flow, revenue, 0050, calendar and warmup set or the seven-method signal generator. Earliest signal date is 2026-10-14. Seal a complete signal only after validating that day's sources and full method selections before next-market-day entry; missing or late inputs stay missing. The August 2026 revenue month is not yet 45 calendar days past month-end on October 13 and cannot be primary-lag eligible today.
