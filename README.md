# VirtuaNES 吞食天地練功助手

Windows 桌面助手，搭配 VirtuaNES 的《吞食天地1中文版》，以遊戲畫面辨識和鍵盤操作自動練功。

## 下載與使用

從 [Releases](https://github.com/TaichungLester/virtuanes-grinding-helper/releases/latest) 下載 Windows ZIP，完整解壓縮後執行 `VirtuaNES練功助手.exe`。請保留旁邊的 `_internal` 與 `VirtuaNES預設` 資料夾。

1. 開啟遊戲，使用 2X 或 3X 視窗模式，保持畫面完整顯示。
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
- 切離遊戲時停止操作；不使用全域啟動快捷鍵，F7 保留給模擬器。
- 不修改遊戲記憶體、不補血、不自動讀檔或覆蓋存檔。

這是依特定遊戲版本與畫面製作的助手，其他字體、濾鏡或版本可能影響辨識。倉庫不包含遊戲 ROM、模擬器或存檔；請自行準備。

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
