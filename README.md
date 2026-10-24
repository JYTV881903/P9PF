# P9PF：csl NRDC 一鍵 SA 政策測試

適用已 root 的 **Pixel 9 Pro Fold（comet）／Android 16**。針對目前數據 SIM 的 `carrier_nr_availabilities_int_array=[1]`，暫時允許 `[1,2]`（NSA＋SA），以排除已觀察到的 SA 政策限制。

**這是 SA 政策測試，不代表手機已具備或已連上 csl n78＋n257 NRDC。** 已是 `[1,2]` 的數據 SIM 不重寫；不修改 NRDC NV、mmWave 頻段或功率設定。

[下載一鍵 SH](https://github.com/JYTV881903/P9PF/raw/refs/heads/main/scripts/pixel9-csl-sa-oneclick.sh) · [檢視 SH](scripts/pixel9-csl-sa-oneclick.sh)

手機長按下載連結，選「下載連結」，保持檔名 `pixel9-csl-sa-oneclick.sh`。只需這一個檔案，所需 DEX 程式已內含，不用解壓 ZIP 或安裝 Java。

若終端機提示符是 `$`，先**單獨輸入 `su`**，允許 root，等到提示符變成 `#` 後，再單獨執行：

```sh
/system/bin/sh /sdcard/Download/pixel9-csl-sa-oneclick.sh
```

預設會識別數據 SIM、保存原有效值、暫時允許 SA＋NSA並等待讀回；其他 CarrierConfig 鍵保留。成功時可看到 `VERIFIED: merged key is [1, 2]`。這只表示設定生效；套用後直接到同一 csl 測試位置確認連線，**本次暫時覆寫在正常重啟後會失效**。

Download 會產生 `P9PF-SA-report-…txt`。回傳這份報告即可；它只含訂閱／slot 編號、版本、目標鍵與已過濾的 CarrierConfig，不包含完整 dump、IMSI 或 ICCID。

只查看目前狀態：

```sh
/system/bin/sh /sdcard/Download/pixel9-csl-sa-oneclick.sh status
```

還原可正常重新啟動手機，移除本次非持久覆寫；或用程式顯示的**完整備份檔案路徑**恢復保存的有效值：

```sh
/system/bin/sh /sdcard/Download/pixel9-csl-sa-oneclick.sh restore /data/local/tmp/p9pf-nrdc/sa-policy/run-實際編號/backup.properties
```

單鍵 restore 會把保存的有效值 `[1]` 放回暫時層，保留其他覆寫鍵；它不等同恢復原先「未設定」的層狀態，正常重啟才會移除此測試的暫時覆寫。出錯、強制中止或 SELinux／Binder 拒絕時，請保留報告；Android 自動還原不保證完成。

程式有來源、編譯紀錄及雜湊校驗：[Java 原始碼](android/NrSaPolicy.java)、[建置資料](android/nr-sa-policy.build.json)、[一鍵檔產生器](tools/build_sa_oneclick.py)。不需要變更 build 類型或停用 SELinux。

原始調校腳本分析、NV 工具及驗證範圍見 [CSL_NRDC.md](CSL_NRDC.md)。單鍵交易、非同步回覆、訂閱切換及封裝已做主機測試；Android 實機 Binder 呼叫、N1／SA 生效及 csl NRDC 連線仍待驗證。
