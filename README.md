# VirtuaNES 吞食天地練功助手

Windows 桌面助手，針對 **FC／NES《吞食天地 1》中文版 ROM（遊戲名稱《吞食天地1中文版》）** 製作，以 VirtuaNES 的遊戲畫面辨識和鍵盤操作自動練功。

## 適用 ROM 與執行環境

| 項目 | 本次使用及驗證的環境 |
| --- | --- |
| 遊戲／ROM | **FC／NES《吞食天地 1》中文版 `.nes` ROM**，遊戲內武將、兵力頁與戰鬥訊息均為中文 |
| 模擬器 | **VirtuaNES 中文介面版（VirtuaNES_cht）**，沿用系統預設按鍵；本次執行檔的檔案版本資訊為 `0.92`，此數值為檔案中繼資料 |
| 作業系統 | **Windows 11，64 位元（x64）**；其他 Windows 版本、macOS、Linux 尚未完整驗證 |
| 畫面設定 | **視窗模式，2X 或 3X**；整個遊戲畫面須完整可見，保持遊戲在前景，不能最小化或被遮住 |
| 執行檔使用 | 完整解壓縮 Windows ZIP；**不需要自行安裝 Python**，必須保留 `_internal`、`VirtuaNES預設` |
| 原始碼執行 | 本次開發與打包使用 **Python 3.12.14，64 位元**；依賴版本見 [requirements.txt](requirements.txt) |

**中文版 ROM 是必要條件。** 本助手依目前這份中文版的文字、字體和版面調校，不適用《吞食天地 2》或網頁版。日文版、英文版、其他漢化補丁、改版與不同模擬器均未驗證。尚未記錄目前 ROM 的漢化補丁版本與校驗碼，不能保證所有同名「中文版」都相容。

本專案及下載包**不包含 ROM、VirtuaNES 模擬器或遊戲存檔**，請自行準備。

## 下載與使用

從 [Releases](https://github.com/TaichungLester/virtuanes-grinding-helper/releases/latest) 下載 Windows ZIP，完整解壓縮後執行 `VirtuaNES練功助手.exe`。請保留旁邊的 `_internal` 與 `VirtuaNES預設` 資料夾。

1. 用 VirtuaNES 中文介面版載入《吞食天地 1》**中文版 ROM**，沿用預設按鍵，使用 2X 或 3X 視窗模式，遊戲須處於未暫停狀態。
2. 在助手按 **Enter** 或「開始」，**10 秒內切回遊戲**。
3. 助手在原野按 V 讀取兵力，再左右移動遇敵、按右與 Z（A）發動總攻。
4. 勝利與升級訊息會逐頁按 A，直到原野；再重新檢查兵力。
5. 遊戲中按 **Esc** 停止，也可使用助手「停止」按鈕。

完整操作見 [使用說明](docs/使用說明.md)。建議首次先在 V 兵力頁使用「只檢查畫面／兵力」，確認讀值。

## 功能與行為

- 支援可見的五至七人名單；排除軍師後，依順序取前五位出戰武將，並自動更新兵力上限。
- **戰鬥中不檢查兵力，持續打到結束。** 戰後才檢查，任一出戰武將嚴格低於門檻就停止並提醒；預設 50%。
- 支援戰後經驗值與升級對話；不綁定武將姓名。
- 停止時只停止送出按鍵，**不按 P、不切換模擬器暫停**。
- 切離遊戲時停止操作；不使用全域啟動快捷鍵。
- 不修改遊戲記憶體、不補血、不自動讀檔或覆蓋存檔。

其他字體、畫面濾鏡或 ROM 版本可能影響辨識，換環境後請先使用兵力唯讀檢查。

## 從原始碼執行

開發與打包環境為 Windows、Python 3.12。於專案目錄執行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe virtuanes.py
```

`virtuanes.py` 是本專案的入口，`bot.py` 提供共用介面與流程；請使用前者啟動。

## 打包 Windows 執行版

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe -m PyInstaller --noconfirm --windowed --onedir --name VirtuaNES練功助手 --collect-all rapidocr_onnxruntime --collect-all onnxruntime virtuanes.py
Copy-Item -Recurse -LiteralPath VirtuaNES預設 -Destination dist/VirtuaNES練功助手/VirtuaNES預設
Copy-Item -LiteralPath docs/使用說明.md -Destination dist/VirtuaNES練功助手/使用說明.md
```

## 流程測試

```powershell
.venv/Scripts/python.exe tests/test_battle_flow.py
.venv/Scripts/python.exe tests/test_no_pause.py
```

這兩個測試使用模擬輸入，驗證戰後才檢查兵力、連續確認多頁訊息及不觸發暫停，不會操作桌面。它們不取代實際遊戲畫面的辨識測試。
