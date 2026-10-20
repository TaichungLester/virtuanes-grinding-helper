"""Preconfigured VirtuaNES frontend: no manual rectangle selection."""
import ctypes
from ctypes import wintypes
import json
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps
import bot

bot.NAMES[:] = ['第1位', '第2位', '第3位', '第4位', '第5位']
u = bot.u
u.GetForegroundWindow.restype = wintypes.HWND
u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
u.GetMenu.argtypes = [wintypes.HWND]
u.GetMenu.restype = wintypes.HMENU
u.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
u.GetSubMenu.restype = wintypes.HMENU
u.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
u.GetMenuState.restype = wintypes.UINT
u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
u.SendMessageTimeoutW.restype = wintypes.LPARAM
PROFILE = bot.ROOT / 'VirtuaNES預設'


class NativeApp(bot.App):
    def __init__(self):
        self.disable_hotkeys = True
        self.direct_total_attack = True
        self.check_hp_after_battle = True
        self.auto_pause_on_stop = False
        bot.DATA = PROFILE
        PROFILE.mkdir(exist_ok=True)
        cfg_path = PROFILE / 'config.json'
        if not cfg_path.exists():
            cfg_path.write_text(json.dumps({'rects': {'game': [0, 0, 640, 448],
                **{f'status_hp{i}': [210, 237 + 32*i, 410, 259 + 32*i] for i in range(5)}},
                'maxima': [100, 100, 161, 110, 104], 'threshold': 50}, ensure_ascii=False), 'utf-8')
        config = json.loads(cfg_path.read_text('utf-8'))
        config['start_delay'] = 10
        cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), 'utf-8')
        super().__init__()
        self.bind('<Return>', lambda event:self.start())
        self.bind('<Escape>', lambda event:self.stop('Esc 手動停止'))
        self.title('VirtuaNES 吞食天地練功｜已預設辨識範圍')
        self.geometry('800x450')
        for widget in self.winfo_children():
            if isinstance(widget, ttk.Notebook):
                widget.pack_forget()
            if isinstance(widget, ttk.Label) and 'F8' in str(widget.cget('text')):
                widget.configure(text='助手視窗按 Enter 開始　｜　遊戲中按 Esc 停止　｜　不使用全域啟動快捷鍵')
            if isinstance(widget, ttk.LabelFrame):
                widget.configure(text='出戰第 1～5 位兵力上限（每次從兵力頁自動更新）')
        self.status.set('範圍已設定。開著 VirtuaNES，先按「只檢查畫面／兵力」確認即可。')
        self.anchors = {k: cv2.cvtColor(np.array(Image.open(PROFILE / (k+'.png')).convert('RGB')), cv2.COLOR_RGB2GRAY)
                        for k in ['status', 'menu']}
        if (PROFILE / 'victory.png').exists():
            self.anchors['victory'] = cv2.cvtColor(np.array(Image.open(PROFILE/'victory.png').convert('RGB')), cv2.COLOR_RGB2GRAY)
        self.menu_position = None
        self.last_state = None

    def validate(self):
        self.save()
        for key in ['status', 'menu']:
            if not (PROFILE / (key+'.png')).exists():
                raise ValueError('預設圖片不完整，請完整解壓縮')
        self.templates = self.anchors

    def check_focus(self):
        handle, title = self.active()
        if not handle or handle != self.target or not title.startswith('VirtuaNES - ') or '吞食天地' not in title:
            raise RuntimeError('已切離 VirtuaNES 遊戲，停止操作')
        if u.IsIconic(handle):
            raise RuntimeError('模擬器已最小化，停止操作')

    def grab(self):
        self.check_focus()
        rect = wintypes.RECT()
        if not u.GetClientRect(self.target, ctypes.byref(rect)):
            raise RuntimeError('無法取得遊戲視窗')
        point = wintypes.POINT(0, 0)
        if not u.ClientToScreen(self.target, ctypes.byref(point)):
            raise RuntimeError('無法取得遊戲位置')
        width, height = rect.right, rect.bottom
        if width < 256 or height < 200:
            raise RuntimeError('遊戲視窗過小')
        shot = ImageGrab.grab(bbox=(point.x, point.y, point.x+width, point.y+height), all_screens=True).convert('RGB')
        return shot.resize((640, 448), Image.Resampling.NEAREST)

    def press(self, vk, duration=.12):
        self.check_focus()
        if self.stop_event.is_set():
            raise RuntimeError('已停止')
        scan = u.MapVirtualKeyW(vk, 0)
        flags = 1 if vk in [0x25, 0x26, 0x27, 0x28] else 0
        u.keybd_event(vk, scan, flags, 0)
        try:
            end = time.monotonic() + duration
            while time.monotonic() < end:
                if self.stop_event.wait(.015):
                    break
                self.check_focus()
        finally:
            u.keybd_event(vk, scan, flags | 2, 0)
        self.stop_event.wait(.35)

    def pause_game(self):
        # Stopping this helper must never toggle the emulator's pause state.
        return False

    def locate(self, shot, key, area):
        gray = cv2.cvtColor(np.array(shot.crop(area)), cv2.COLOR_RGB2GRAY)
        template = self.anchors[key]
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, position = cv2.minMaxLoc(result)
        return score, (position[0]+area[0], position[1]+area[1])

    def menu_text(self, shot):
        area = (160, 240, 560, 448)
        result, _ = self.engine(np.array(shot.crop(area)))
        return result or [], area

    def state(self, shot):
        state = self.detect_state(shot)
        if state != self.last_state:
            self.last_state = state
            shot.save(PROFILE / f'最近畫面-{state}.png')
            self.say('目前畫面：' + {'map': '地圖', 'status': '兵力頁', 'menu': '戰鬥選單', 'battle': '戰鬥中', 'victory': '勝利', 'unknown': '等待辨識'}.get(state, state))
        return state

    def detect_state(self, shot):
        self.menu_position = None
        if self.locate(shot, 'status', (140, 20, 300, 120))[0] >= .96:
            return 'status'
        hsv = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2HSV)
        green = ((hsv[:, :, 0] > 25) & (hsv[:, :, 0] < 95) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 70)).mean()
        if green > .22:
            return 'map'
        for i in range(5):
            self.cfg['rects'][f'battle_hp{i}'] = [71, 49+48*i, 159, 66+48*i]
        if 'victory' not in self.anchors and (PROFILE/'victory.png').exists():
            self.anchors['victory'] = cv2.cvtColor(np.array(Image.open(PROFILE/'victory.png').convert('RGB')), cv2.COLOR_RGB2GRAY)
        if 'victory' in self.anchors and self.locate(shot, 'victory', (160, 240, 620, 448))[0] >= .95:
            return 'victory'
        menu_score, (mx, my) = self.locate(shot, 'menu', (320, 260, 490, 380))
        if menu_score >= .95:
            self.menu_position = (mx, my, my+self.anchors['menu'].shape[0])
            colored = hsv[:250, 260:420]
            if ((colored[:, :, 1] > 110) & (colored[:, :, 2] > 100)).mean() > .003:
                return 'battle'
            return 'menu'
        if self.result_dialog(shot):
            return 'victory'
        gray = np.array(ImageOps.grayscale(shot))
        visible_rows = sum((gray[49+48*i:66+48*i, 71:159] > 170).mean() > .025 for i in range(5))
        if visible_rows < 3:
            return 'unknown'
        result, area = self.menu_text(shot)
        text = ''.join(str(r[1]) for r in result)
        if '取勝' in text or '取胜' in text:
            return 'victory'
        for box, text, confidence in result:
            if ('總攻' in text or '总攻' in text) and confidence >= .8:
                self.menu_position = (min(p[0] for p in box)+area[0], min(p[1] for p in box)+area[1],
                                      max(p[1] for p in box)+area[1])
                return 'menu'
        return 'battle'

    @staticmethod
    def result_dialog(shot):
        # Battle results and all level-up pages share a wide, closed frame.
        # The command menu is narrower; the status panel starts at the left edge.
        gray = np.array(ImageOps.grayscale(shot))
        mask = (gray > 100).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if 170 <= x <= 240 and 250 <= y <= 330 and 350 <= width <= 420 and 90 <= height <= 180:
                edge = mask[y:y+height, x:x+width]
                if min(edge[:4].mean(), edge[-4:].mean(), edge[:, :4].mean(), edge[:, -4:].mean()) > .35:
                    return True
        return False

    def score(self, shot, key):
        if key == 'selected':
            if self.menu_position is None:
                return 0
            x, top, bottom = self.menu_position
            # Cursor is a small white triangle immediately left of the label.
            crop = np.array(shot.crop((max(0, int(x)-28), int(top), max(1, int(x)-5), int(bottom)+2)))
            white = np.all(crop > 190, axis=2).astype(np.uint8)
            count, _, stats, _ = cv2.connectedComponentsWithStats(white)
            return 1.0 if any(8 <= s[4] <= 110 and 3 <= s[2] <= 15 and 4 <= s[3] <= 19 for s in stats[1:]) else 0.0
        return 0.0

    def hp_once(self, shot, prefix):
        if prefix == 'status':
            rows = []
            for i in range(7):
                numeric_area = np.array(ImageOps.grayscale(shot.crop((180, 205+32*i, 410, 227+32*i))))
                if int((numeric_area > 100).sum()) < 5:
                    if i < 5:
                        raise ValueError('出戰名單尚未完整顯示，先停止')
                    break
                # Read the two numeric columns separately: the FC slash and
                # scanline filter otherwise distort the recognizer's line box.
                current, maximum = [self.status_number(shot.crop((left, 205+32*i, right, 227+32*i)))
                                    for left, right in [(180, 280), (300, 410)]]
                if not 0 <= current <= maximum or maximum <= 0:
                    raise ValueError('兵力頁讀值無效')
                rows.append((current, maximum))
            # Compare the advisor label with each visible row by pixels. No
            # character name or fixed party index is embedded in this mapping.
            advisor = cv2.cvtColor(np.array(shot.crop((481, 259, 559, 288))), cv2.COLOR_RGB2GRAY)
            matches = []
            for i in range(len(rows)):
                area = cv2.cvtColor(np.array(shot.crop((35, 189+32*i, 130, 228+32*i))), cv2.COLOR_RGB2GRAY)
                score = cv2.minMaxLoc(cv2.matchTemplate(area, advisor, cv2.TM_CCOEFF_NORMED))[1] if np.std(advisor) > 3 else 0
                if score >= .94:
                    matches.append(i)
            advisor_blank = int((advisor > 80).sum()) < 5
            if not advisor_blank and len(matches) != 1:
                raise ValueError('無法確認目前軍師，停止以免使用錯誤的兵力上限')
            chosen = (rows if advisor_blank else [row for i, row in enumerate(rows) if i != matches[0]])[:5]
            if len(chosen) != 5:
                raise ValueError('無法確認五位出戰武將，先停止')
            self.cfg['maxima'] = [row[1] for row in chosen]
            self.events.put(('maxima', self.cfg['maxima'][:]))
            self.cfg['last_status_currents'] = [row[0] for row in chosen]
            self.cfg['party_checked'] = True
            return [row[0] for row in chosen]
        values = []
        for i, maximum in enumerate(self.cfg['maxima']):
            crop = shot.crop(self.cfg['rects'][f'{prefix}_hp{i}'])
            value = self.status_number(crop)
            values.append(bot.read_hp(str(value), 1.0, maximum))
        if not self.cfg.get('party_checked'):
            bootstrap = self.cfg.get('verified_battle')
            if bootstrap and time.time() < bootstrap.get('expires', 0) and values == bootstrap.get('currents'):
                self.cfg['party_checked'] = True
                self.cfg.pop('verified_battle', None)
                self.config_path.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), 'utf-8')
                self.say('目前戰鬥五人的兵力與剛才已確認的隊伍一致。')
            else:
                raise ValueError('請先回地圖按 V 檢查當前隊伍，再開始練功')
        return values

    def status_number(self, crop):
        readings = []
        text, confidence = bot.recognize_number(self.engine, crop)
        if bot.re.fullmatch(r'\d{1,5}', text) and confidence >= .90:
            readings.append(int(text))
        for threshold in [80, 100, 120]:
            binary = ImageOps.grayscale(crop).point(lambda value: 255 if value > threshold else 0)
            bounds = binary.getbbox()
            if bounds is None:
                raise ValueError('兵力欄位尚未顯示數字')
            binary = binary.crop(bounds)
            binary = ImageOps.expand(ImageOps.invert(binary).resize((binary.width*3, binary.height*3)),
                                    border=15, fill=255).convert('RGB')
            result, _ = self.engine(np.array(binary), use_det=False, use_cls=False)
            if not result or len(result) != 1:
                continue
            text = bot.re.sub(r'\s+', '', str(result[0][0]))
            if not bot.re.fullmatch(r'\d{1,5}', text) or float(result[0][1]) < .90:
                continue
            readings.append(int(text))
        if len(readings) < 2 or len(set(readings)) != 1:
            raise ValueError('兵力數字無法取得兩次一致的可靠辨識，先停止')
        return readings[0]

    def diagnose(self):
        if self.running or self.diagnosing:
            return
        self.diagnosing = True
        self.say('3 秒後讀取 VirtuaNES，請切到遊戲；這項檢查不會按遊戲按鍵。')
        def run():
            try:
                time.sleep(3)
                self.target, _ = self.active()
                self.check_focus()
                if self.engine is None:
                    self.engine = bot.RapidOCR()
                shot = self.grab()
                state = self.state(shot)
                if state in ['status', 'menu', 'battle']:
                    values = self.hp_once(shot, 'status' if state == 'status' else 'battle')
                    self.say('唯讀兵力：' + '、'.join(f'{n} {h}/{m}' for n, h, m in zip(bot.NAMES, values, self.cfg['maxima'])))
                else:
                    self.say('請在遊戲內按 V 顯示兵力，再執行一次唯讀檢查。')
            except Exception as e:
                self.say('檢查未通過：' + str(e))
            finally:
                self.diagnosing = False
        bot.threading.Thread(target=run, daemon=True).start()

    def worker(self):
        self.cfg['party_checked'] = False
        super().worker()

    def poll(self):
        if self.running and self.active()[0] == self.target and u.GetAsyncKeyState(0x1B) & 0x8001:
            self.stop('Esc 緊急停止')
        super().poll()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        app = NativeApp()
        app.withdraw()
        app.update_idletasks()
        bot.RapidOCR()
        Path(sys.argv[2]).write_text(json.dumps({'gui': 'ok', 'model': 'ok', 'preset': 'VirtuaNES'}), 'utf-8')
        app.destroy()
    else:
        NativeApp().mainloop()
