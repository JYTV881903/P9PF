# P9PF：csl NRDC 手機測試

在已 root 的 Pixel 9 Pro Fold 上檢查 csl n78＋n257 NRDC。手機直接操作即可，預設只讀取設定。腳本的成功訊息表示 NV 讀回一致，尚不代表已連上 NRDC。

先關閉 NSG、其他診斷 App 及正在執行的調校腳本，再依序操作：

1. 用手機瀏覽器[下載 ZIP](https://github.com/JYTV881903/P9PF/archive/refs/heads/main.zip)。
2. 用手機檔案管理器解壓到 Download，確認裡面有 `P9PF-main/scripts/pixel9-phone.sh`。
3. 開啟支援 root 的終端機，例如 [Termux](https://github.com/termux/termux-app/releases)。Termux 第一次使用可先執行 `termux-setup-storage`，允許儲存空間存取。
4. 在終端機輸入以下兩行，並在 root 管理器允許請求：

```sh
su
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh audit
```

如果檔案管理器多建立一層資料夾，請將指令中的路徑換成實際解壓位置。透過 `/system/bin/sh` 讀取腳本即可，不需要 `chmod`。

完成後，Download 會出現 `P9PF-NRDC-report-日期時間-編號.txt`。回傳這份檔案即可；原值備份、原始 AT 回覆及完整系統 dump 不會複製到公開報告。報告包含 NV／CarrierConfig 的成功或失敗狀態；發生錯誤也不會自動改設定。

若讀回 NRDC 旗標為 `00`，可明確執行雙旗標啟用測試：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh enable-both
```

此操作先備份，再把原稿已有的兩個 NRDC 旗標設為 `01`，逐筆讀回；失敗時嘗試還原。原本已是 `01` 的項目不重寫。保存顯示的 `Backup` 路徑後，正常重新啟動手機，再執行 `audit`。

若需還原，將 `run-...` 換成該次啟用顯示的備份目錄：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh restore /data/local/tmp/p9pf-nrdc/run-...
```

還原範圍只包括這次工具保存的 NRDC 旗標。若手機失去電源、整個程序被強制殺死或 AT port 持續失效，自動還原可能無法完成，請保留備份。

若兩個旗標本來就是 `01`，下一步查有效 SA 政策及 n78＋n257 的 UE Capability 組合，不要反覆重寫相同值。

詳細分析、來源、原稿覆寫問題與驗證限制見 [CSL_NRDC.md](CSL_NRDC.md)。核心邏輯與手機入口已做主機端模擬測試；Android mksh／Toybox、實際 NV 與 csl NRDC 尚待手機驗證。
