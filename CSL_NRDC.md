# P9PF：csl n78＋n257 NRDC 的腳本調整

這版是針對你**目前已能使用 csl mmWave** 的手機做 NRDC 增量測試，並非重置後的完整 mmWave 解鎖套件。目標是先排除「NRDC 開關根本沒成功寫入」及 Android SA 政策限制，再核對特定 NRDC 組合；目前尚未實機證明能連上 csl NRDC。

已知手機版本：Android 16、`CP1A.260505.005`，基頻 `g5400c-251201-260127-B-14784805`（來自你的畫面）。CarrierConfig 結果見下一節；SIM 是本地或漫遊及空中能力宣告仍待確認。

## 已取得的手機報告與下一步

後續唯讀報告確認兩個 `NrDcSupport` 旗標都已是 `01`。Phone Id 0 的有效 `carrier_nr_availabilities_int_array` 為 `[1]`，來自 default app；carrier app、persistent override 與 temporary override 層均未新增覆寫。Phone Id 1 為 `[1,2]`。報告未提供當前 default-data subId，不能直接把 Phone Id 0 當作數據 SIM。

因此目前優先使用 [一鍵 SA 政策測試](README.md)。它在執行時識別數據 SIM，僅在有效值恰為 `[1]` 時暫時合併單一鍵 `[1,2]`，並等待非同步 API 讀回。已是 SA 允許狀態便不修改。這與原先 NV `enable-both` 是不同操作；本次無需重寫已啟用的 NRDC NV。

新程式透過 root 的 `ICarrierConfigLoader.overrideConfig` 介面，固定 `persistent=false`，不使用 stock user build 可能拒絕的 `cmd phone cc`。它不清空整個 override bundle；restore 僅恢復備份的有效值到暫時層，正常重啟可移除本次暫時覆寫。保留原值與日誌後才嘗試修改，Binder／SELinux／反射權限不符會報錯。

獨立 IMS N1 禁止原因仍可能存在；`[1,2]` 生效只排除 carrier 的這一項 SA 限制。網路是否配置 NRDC，仍須站點實測與 RRC／能力紀錄確認。傳輸逾時或硬中止後，當下讀到 `[1]` 也不證明先前排隊的覆寫已取消；此時保留備份與報告，正常重啟可結束暫時測試。主機上的 shutdown-hook 測試不代表 Android ART 必然在訊號終止時執行自動還原。

## 原稿的具體問題

已保留並分析 `pixel9-tuning-250714v2.sh`，沒有在手機執行它。原稿 SHA-256：`4f44ce6dde17cf9c049eca589411b5d4fda68121f8d5b36780d8a073ae6b8fb5`。

- 共 172 次 NV 寫入，169 組不同鍵／索引；沒有逐筆讀回、原值備份或完整錯誤處理。
- NRDC 段本來就寫了 `!NRCOMMON.NrDcSupport`、`!NRCOMMON.NrDcSupport_DS`，index 0，值 `01`。問題不能簡化成「原稿少了 NRDC 開關」。
- 11 段 `echo ... > /dev/umts_router & cat /dev/umts_router` 沒有交易逾時、逐筆回覆關聯或完成檢查。相關 s5400 驅動在短暫無資料時可回傳 0，因此 `cat` 可能提早結束；在其他狀態也可能持續等待。終端看似跑完不代表全部命令生效。
- JP 表 `OEM_GFEATURE_FCC_CT3_GLOBAL_MMW_JP_NRSA_BANDS` 的 index 1 被依次寫成 `01,00`、`02,00`、`1c,00`、`4e,00`。如果全部寫入成功，最後只留下 `4e,00`，不會同時加入四個頻段。
- 不能直接把最後三筆改成 index 10／11／12，或把表頭 9 改成 18：原稿的 10–18 很像另兩組「數量＋清單」，格式未被證實。已經改過的表也不能在沒有原值時憑猜測恢復。
- FR1／FR2 mask、FBI、地區清單、功率類別及 AS release 欄位缺少此版基頻的公開格式證據。宣告頻段或提高 release 數字，不能建立未實作的 NRDC band combination。

`n78_n257K` 中的 K 是頻寬類別標記，不是要填入 NV 的字串。這次沒有假造組合鍵名、位元遮罩或 K 對應的載波數。

## 新版改了甚麼

主檔：`scripts/pixel9-csl-nrdc.sh`。

- 預設 `audit`，只讀取。`enable` 才會嘗試寫入原稿已有的兩個 NRDC 旗標。
- `GET` 使用已核對的 `AT+GOOGGETNV="鍵名"`，不帶 index；僅接受該鍵 index 0 的單一、精確 `00`／`01` 回覆及 terminal `OK`。
- 同一讀寫 FD 完成一次請求／回覆，使用真正 CR 結尾、逐筆序列化及外部逾時；短暫 idle read 不當作交易成功。
- 必須先完整備份本次選定旗標。寫入前記錄原值，寫後讀回；任何失敗都嘗試恢復本次已觸碰的原值，並驗證恢復結果。若連回復也失敗，會明確報錯並保留備份。
- 原值不是 `00`／`01`、GET 不支援、回覆格式不同或缺少工具時，停止而不猜測預設值。
- 已是 `01` 的鍵不重寫。保留目前頻段、mmWave、地區、功率及其他 NV 設定，不自動重啟手機或切換無線電。
- 備份是白名單 TSV 資料，不會作為 shell 程式執行。`restore` 僅還原該次備份中的旗標，不能還原舊原稿已改過的其他 NV 項目。

`main`、`ds`、`both` 對應主鍵、`_DS` 鍵、兩鍵；不假設它們必然等同 Android 的實體 SIM 卡槽編號。預設只處理 `main`，下列測試明確選 `both`，與原稿兩鍵範圍一致。

## 手機直接操作

使用手機瀏覽器下載本儲存庫 ZIP，以檔案管理器解壓至 Download，並在可取得 root 的手機終端機操作。完整入門步驟見 [README.md](README.md)。若使用 Termux，可先執行 `termux-setup-storage` 並允許儲存空間存取，再輸入 `su`。

先完全關閉 NSG、其他診斷 App 及原稿的執行工作；不要同時有別的程式讀寫 AT port。社群工具建議關閉診斷 App 後可等約一分鐘讓連線釋放。新版的鎖只約束本工具，不能替其他 App 排程。

在 root 終端機執行：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh audit
```

手機入口會逐一執行 NV 唯讀 audit 與已過濾的 CarrierConfig 檢查，保留兩者退出狀態，再產生 `Download/P9PF-NRDC-report-日期時間-編號.txt`。只需回傳這份文字報告。它不包含 `backup.tsv`、`touched.tsv`、`reply-N.txt`、完整系統 dump 或其他私人日誌。

若檔案管理器多解壓一層資料夾，請修改路徑。透過系統 shell 讀取腳本，不需要在共享儲存區執行二進位檔或使用 `chmod`；入口會使用 Android 系統 PATH，不依賴 Termux 的額外套件。

若主旗標或 DS 旗標目前是 `00`，可明確執行這次最小變更：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh enable-both
```

若兩旗標原本已是 `01`，這個命令不會有新增效果，應直接沿下一節檢查 SA 政策及 UE 能力。不要為求變化而先改成 `00` 再改回。

成功訊息只表示當下 NV 讀回一致。保存顯示的 `Backup` 路徑後，正常重新啟動手機，重跑 `audit` 確認保留，再到同一 csl 測試位置觀察 NRDC。這裡沒有自動重開機，便於先記下備份及結果。

若需恢復，將下列 `run-...` 換成**你要還原那次 enable 的目錄**：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-phone.sh restore /data/local/tmp/p9pf-nrdc/run-...
```

Restore 會先備份還原操作前的現值，再寫入原先保存的值及讀回；它也不重啟手機。不要刪除備份、清空 EFS 或套用別部手機的 NV 值。

自動還原需要程序及 AT port 仍可工作；斷電、強制殺死整個程序或 port 持續失效時，無法保證自動恢復。備份會留在手機，之後可用 `restore` 核對並還原。下載報告匯出失敗時，手機入口會顯示保留在 `/data/local/tmp/p9pf-nrdc/phone-.../report.txt` 的私人報告位置。

若要分別執行核心與政策檢查，也可在 root 終端機使用：

```sh
/system/bin/sh /sdcard/Download/P9PF-main/scripts/pixel9-csl-nrdc.sh audit --slot both
/system/bin/sh /sdcard/Download/P9PF-main/tools/audit_nr_carrier_config.sh
```

## 為甚麼還要查 Android 的 SA 政策

Android 16 的有效 `carrier_nr_availabilities_int_array` 若不含 `2`，framework 可加入 carrier 的 N1／SA 禁止原因。即使 modem 的 NRDC NV 是 `01`，這一層仍可能妨礙 SA／NRDC。

`tools/audit_nr_carrier_config.sh` 只輸出 Phone Id、來源層標題及兩個 NR 欄位，不匯出完整 dump。讀取代碼：`1=NSA`、`2=SA`；`[1,2]` 允許兩者，但不證明 NRDC。必須按該 Phone Id 的覆寫層判讀，不能只看全域預設 `[1,2]`；最後的 `mNoSimConfig` 不是有效 SIM 的政策。

`additional_nr_advanced_bands_int_array` 是圖示分類，不能拿來啟用或驗收 NRDC。這次不變更 CarrierConfig；若有效政策確實缺少 SA，應針對這個已觀察到的限制另行處理，而非繼續重寫 NV。

## 依結果走下一步

| 實測結果 | 下一個需要處理的位置 |
|---|---|
| GET 不支援／值或格式不同 | 核對這版基頻的實際回應；新版停止寫入 |
| NV 原本 `00`，enable 後及重啟後為 `01` | 到 csl 測試位置，核對能力宣告及 NRDC 設定 |
| NV 已是 `01`，有效 CarrierConfig 不允許 SA | Android／電信商 SA 政策，不能靠重複同一 NV 寫入處理 |
| SA 允許，但未確認 n78＋n257 的 NRDC 組合 | 收集 UE Capability；缺少一段或被網路過濾的能力訊息不能直接判成硬體不支援 |
| 目標組合已宣告但網路未配置 | 檢查同 SIM／同站點下的 RRC 流程、拒絕或釋放原因 |

需要的最小空中紀錄是 `UECapabilityEnquiry`、完整／分段重組後的 `UECapabilityInformation`，以及該次 `RRCReconfiguration`／`CellGroupConfig`。核對 n78／n257 的同一組 band combination、`nrdc-Parameters`、`ca-ParametersNRDC` 及參照的 feature sets。驗收要看到 NR MCG／NR SCG 的配置與兩組在負載下同時排程；只列出六個 n257 或跑速增加不足以區分 NR CA 與 NRDC。

## 證據來源及驗證範圍

- [社群 NRDC 實作：兩個既有鍵及值 01](https://github.com/davwheat/shannon-pixel-modem-tweaks-app/blob/e839d46d68e1a590d77a6682104ee89a9d3ce11c/app/src/main/java/dev/davwheat/shannonmodemtweaks/tweaks/nvitems/NrDcSupport.kt)。這是社群程式證據，不是 Google 對此手機／基頻的 NRDC 保證。
- [GET／SET 社群實作](https://github.com/davwheat/shannon-pixel-modem-tweaks-app/blob/e839d46d68e1a590d77a6682104ee89a9d3ce11c/app/src/main/java/dev/davwheat/shannonmodemtweaks/tweaks/nvitems/NvItemTweak.kt)。新版沒有沿用其僅搜尋 `ok` 的寬鬆判定。
- [s5400 驅動原始碼：read／release](https://github.com/CodeLinaro-mirror/la_kernel_google-modules_radio_samsung_s5400/blob/66bc6239dfb1cd9ee9cf47bf942f48024d6bec22/ipc_io_device.c)。這是公開舊分支的傳輸行為證據，不是已確認與你的 CP1A 核心完全相同。
- [Android 16 CarrierConfig 定義](https://github.com/aosp-mirror/platform_frameworks_base/blob/99b01a65cc4c104933788b3143285ab6bae65827/telephony/java/android/telephony/CarrierConfigManager.java) 及 [N1／SA 使用端](https://github.com/aosp-mirror-neo/platform_frameworks_opt_telephony/blob/3449e9e2cd2738d8cdeb88514498f728622e3a6b/src/java/com/android/internal/telephony/GsmCdmaPhone.java#L2501)。
- [TS 38.331 ASN.1 的公開實作](https://github.com/srsran/srsRAN_Project/blob/main/include/srsran/asn1/rrc_nr/ue_cap.h)，用來核對 NRDC／頻寬類別欄位，沒有據此推導未知 NV 格式。

主機已測試 NV 交易、CarrierConfig 過濾、手機入口、Java 單鍵交易與反射合約、非同步回覆及單檔封裝。測試包含 CR 分隔、短暫 idle／分段回覆、先備份後寫入、回覆遺失、還原、損壞備份拒絕、訂閱切換、排隊寫入與報告範圍。Java 測試使用主機端 Android／Binder 替身，沒有把這些替身封裝到手機程式。

手機已完成舊版 `audit`，證實 GET 讀回、CarrierConfig 分層及 Download 報告匯出可用。後續一鍵 SH 實機報告也確認 Android 16 `CP1A.260505.005` 上的 Binder 存取與單鍵套用成功：數據 SIM 位於 slot 0，合併後政策由 `[1]` 變成 `[1,2]`，temporary override 層與讀回一致，persistent 層未新增覆寫。原 default app 的 `[1]` 仍存在是正常的分層行為；目前由後面的 temporary 層覆蓋。

**SA／N1 空中註冊、csl NRDC 配置與同時排程仍待站點測試。** 主機的訊號／shutdown-hook 測試不保證 Android 上的自動還原；正常重啟會結束這次暫時覆寫。
