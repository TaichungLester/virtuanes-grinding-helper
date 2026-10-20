"""FC 吞食天地：可校準、遇到不確定狀況即停止的畫面練功助手。"""
import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageTk, ImageOps
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA = ROOT / '設定'
NAMES = ['劉備', '關羽', '張飛', '宋仁', '宋勇']
TEMPLATES = {'map': '地圖草地（只框一小塊純草地）', 'status': '兵力頁標題「大將」',
             'battle': '戰鬥中「劉備」姓名（不含數字）', 'menu': '戰鬥選單「總攻」文字',
             'selected': '選中總攻時：左側箭頭＋總攻文字',
             'victory': '勝利訊息「的戰鬥中取勝」文字'}
u = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


class LowHP(RuntimeError):
    pass


def read_hp(text, confidence, maximum):
    """Never silently repair OCR or accept a partial number."""
    if confidence < .90:
        raise ValueError('兵力辨識信心不足')
    match = re.fullmatch(r'\s*(\d{1,5})(?:\s*[/／]\s*(\d{1,5}))?\s*', text)
    if not match:
        raise ValueError(f'無法確認兵力：{text!r}')
    current = int(match[1])
    if match[2] and int(match[2]) != maximum:
        raise ValueError('兵力上限已改變，請更新上限設定')
    if not 0 <= current <= maximum:
        raise ValueError('兵力讀值超出上限')
    return current


def recognize_number(engine, crop):
    # The FC font is white on black. Tighten to the digits, invert and pad
    # before recognizing the whole line, avoiding detector-split digits.
    box = ImageOps.grayscale(crop).point(lambda v: 255 if v > 170 else 0).getbbox()
    if box is None:
        raise ValueError('兵力範圍沒有可辨識數字')
    crop = crop.crop(box)
    digit_crop = crop.copy()
    crop = ImageOps.invert(crop).resize((crop.width * 3, crop.height * 3))
    crop = ImageOps.expand(crop, border=15, fill='white')
    result, _ = engine(np.array(crop), use_det=False, use_cls=False)
    if not result or len(result) != 1:
        raise ValueError('兵力無法辨識')
    text = re.sub(r'\s+', '', str(result[0][0]))
    confidence = float(result[0][1])
    if confidence < .90:
        agreed = []
        for threshold in [100, 120]:
            binary = ImageOps.grayscale(digit_crop).point(lambda v: 255 if v > threshold else 0).convert('RGB')
            binary = ImageOps.expand(ImageOps.invert(binary).resize((binary.width*3, binary.height*3)), border=15, fill='white')
            alternate, _ = engine(np.array(binary), use_det=False, use_cls=False)
            if alternate and len(alternate) == 1:
                candidate = re.sub(r'\s+', '', str(alternate[0][0]))
                if candidate == text and float(alternate[0][1]) >= .90:
                    agreed.append(float(alternate[0][1]))
        if len(agreed) == 2:
            confidence = min(agreed)
    return text, confidence


class Selector(tk.Toplevel):
    def __init__(self, owner, screenshot, done):
        super().__init__(owner)
        self.done, self.image, self.origin, self.box = done, screenshot, None, None
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.geometry(f'{screenshot.width}x{screenshot.height}+0+0')
        self.photo = ImageTk.PhotoImage(screenshot)
        self.canvas = tk.Canvas(self, highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        self.canvas.create_text(20, 20, text='拖曳框選；Esc 取消', anchor='nw', fill='red', font=('Microsoft JhengHei', 20, 'bold'))
        self.canvas.bind('<ButtonPress-1>', self.down)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.bind('<Escape>', lambda e: self.finish(None))
        self.focus_force()

    def down(self, e):
        self.origin = (e.x, e.y)
        self.box = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='red', width=3)

    def move(self, e):
        if self.origin:
            self.canvas.coords(self.box, *self.origin, e.x, e.y)

    def up(self, e):
        if self.origin:
            x, y = self.origin
            rect = [min(x, e.x), min(y, e.y), max(x, e.x), max(y, e.y)]
            self.finish(rect if rect[2] - rect[0] >= 8 and rect[3] - rect[1] >= 8 else None)

    def finish(self, rect):
        self.destroy()
        self.done(rect, self.image)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('吞食天地 FC 練功助手')
        self.geometry('800x760')
        DATA.mkdir(exist_ok=True)
        self.config_path = DATA / 'config.json'
        self.cfg = json.loads(self.config_path.read_text('utf-8')) if self.config_path.exists() else {'rects': {}, 'maxima': [314, 114, 114, 110, 104], 'threshold': 50}
        self.events, self.stop_event = queue.Queue(), threading.Event()
        self.running, self.target, self.engine = False, None, None
        self.diagnosing = False
        self.hotkeys = {}
        self.status = tk.StringVar(value='尚未開始。請先閱讀使用說明並完成校準。')
        ttk.Label(self, text='F8 開始／停止　｜　F9 緊急停止　｜　滑鼠切換視窗也會停止', font=('Microsoft JhengHei', 12, 'bold')).pack(pady=8)
        ttk.Label(self, textvariable=self.status, wraplength=770).pack(pady=6)
        controls = ttk.Frame(self)
        controls.pack(fill='x', padx=12)
        ttk.Button(controls, text=f'開始（{self.cfg.get("start_delay", 5)} 秒後切到遊戲）', command=self.start).pack(side='left')
        ttk.Button(controls, text='停止', command=lambda: self.stop('手動停止')).pack(side='left', padx=8)
        ttk.Button(controls, text='只檢查畫面／兵力，不按鍵', command=self.diagnose).pack(side='left')
        self.threshold = tk.StringVar(value=str(self.cfg.get('threshold', 50)))
        ttk.Label(controls, text='停止門檻 %').pack(side='left', padx=8)
        ttk.Entry(controls, textvariable=self.threshold, width=4).pack(side='left')
        maxima = ttk.LabelFrame(self, text='出戰五人兵力上限（升級後必須更新）')
        maxima.pack(fill='x', padx=12, pady=8)
        self.maximum = []
        for i, name in enumerate(NAMES):
            ttk.Label(maxima, text=name).grid(row=0, column=i * 2, padx=4)
            v = tk.StringVar(value=str(self.cfg['maxima'][i]))
            self.maximum.append(v)
            ttk.Entry(maxima, textvariable=v, width=6).grid(row=0, column=i * 2 + 1)
        book = ttk.Notebook(self)
        book.pack(fill='both', expand=True, padx=12)
        page = ttk.Frame(book)
        book.add(page, text='畫面校準')
        ttk.Label(page, text='按框選後有 3 秒可切到遊戲。請保持瀏覽器大小、縮放與捲動位置固定。', wraplength=740).pack(pady=6)
        self.labels = {}
        for key, label in [('game', '整個遊戲畫面（不含網站廣告）'), ('pause', '模擬器工具列「暫停」圖示按鈕')] + list(TEMPLATES.items()):
            row = ttk.Frame(page)
            row.pack(fill='x', pady=3)
            ttk.Button(row, text='框選', command=lambda k=key: self.capture(k)).pack(side='left')
            v = tk.StringVar()
            self.labels[key] = v
            ttk.Label(row, textvariable=v).pack(side='left', padx=8)
            v.set(('✓ ' if key in self.cfg['rects'] else '○ ') + label)
        hp_page = ttk.Frame(book)
        book.add(hp_page, text='兵力數字校準')
        ttk.Label(hp_page, text='戰鬥頁：每人只框目前兵力數字。\nV 兵力頁：每人框完整「目前／上限」，不要包含姓名。').pack(pady=10)
        for prefix, title in [('battle_hp', '戰鬥頁'), ('status_hp', 'V 兵力頁')]:
            frame = ttk.LabelFrame(hp_page, text=title)
            frame.pack(fill='x', pady=8)
            for i, name in enumerate(NAMES):
                key = f'{prefix}{i}'
                ttk.Button(frame, text=f'{name} 框選', command=lambda k=key: self.capture(k)).grid(row=i, column=0, padx=8, pady=3)
                v = tk.StringVar(value='已設定' if key in self.cfg['rects'] else '尚未設定')
                self.labels[key] = v
                ttk.Label(frame, textvariable=v).grid(row=i, column=1)
        self.log = tk.Text(self, height=9, state='disabled')
        self.log.pack(fill='x', padx=12, pady=8)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def say(self, text):
        self.events.put(('log', text))

    def save(self):
        self.cfg['maxima'] = [int(v.get()) for v in self.maximum]
        self.cfg['threshold'] = float(self.threshold.get())
        if any(v <= 0 for v in self.cfg['maxima']) or not 1 <= self.cfg['threshold'] <= 99:
            raise ValueError('兵力上限必須大於零，門檻必須為 1～99')
        self.config_path.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), 'utf-8')

    def capture(self, key):
        if self.running or self.diagnosing:
            return
        self.status.set('3 秒後截取畫面，請切到遊戲。')
        def take():
            self.withdraw()
            def show():
                shot = ImageGrab.grab()
                def done(rect, image):
                    self.deiconify()
                    if rect:
                        self.cfg['rects'][key] = rect
                        if key in TEMPLATES or key == 'pause':
                            image.crop(rect).save(DATA / f'{key}.png')
                        self.labels[key].set('✓ 已設定：' + key)
                        self.save()
                    self.status.set('校準已儲存。')
                Selector(self, shot, done)
            self.after(250, show)
        self.after(3000, take)

    def validate(self):
        self.save()
        keys = ['game', 'pause'] + list(TEMPLATES) + [f'{p}{i}' for p in ['battle_hp', 'status_hp'] for i in range(5)]
        missing = [k for k in keys if k not in self.cfg['rects']]
        if missing:
            raise ValueError('尚未校準：' + ', '.join(missing))
        self.templates = {k: cv2.cvtColor(np.array(Image.open(DATA / f'{k}.png').convert('RGB')), cv2.COLOR_RGB2GRAY) for k in TEMPLATES}

    def start(self):
        if self.diagnosing:
            return
        if self.running:
            return self.stop('手動停止')
        try:
            self.validate()
        except Exception as e:
            return messagebox.showerror('請先完成設定', str(e))
        self.running = True
        self.stop_event.clear()
        self.say(f'{self.cfg.get("start_delay", 5)} 秒後開始，請切到吞食天地遊戲視窗。')
        threading.Thread(target=self.worker, daemon=True).start()

    def stop(self, reason):
        self.stop_event.set()
        self.say(reason)

    def active(self):
        handle = u.GetForegroundWindow()
        title = ctypes.create_unicode_buffer(1024)
        u.GetWindowTextW(handle, title, 1024)
        return handle, title.value

    def check_focus(self):
        handle, title = self.active()
        if handle != self.target or '吞食天地' not in title or not any(x in title for x in ['Chrome', 'Edge', 'Firefox']):
            raise RuntimeError('遊戲視窗失去焦點或分頁已切換，停止操作')

    def press(self, vk, duration=.10):
        self.check_focus()
        if self.stop_event.is_set():
            raise RuntimeError('已停止')
        # Key releases are guaranteed even when an emergency stop occurs.
        flags = 1 if vk in [0x25, 0x26, 0x27, 0x28] else 0
        u.keybd_event(vk, 0, flags, 0)
        try:
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if self.stop_event.wait(.015):
                    break
                self.check_focus()
        finally:
            u.keybd_event(vk, 0, flags | 2, 0)
        self.stop_event.wait(.4)

    def grab(self):
        self.check_focus()
        return ImageGrab.grab().convert('RGB')

    def pause_game(self):
        """Reveal and verify the calibrated pause control before clicking it."""
        self.check_focus()
        left, top, right, bottom = self.cfg['rects']['pause']
        x, y = (left + right) // 2, (top + bottom) // 2
        u.SetCursorPos(x, y)
        time.sleep(.4)
        self.check_focus()
        actual = cv2.cvtColor(np.array(self.grab().crop((left, top, right, bottom))), cv2.COLOR_RGB2GRAY)
        expected = cv2.cvtColor(np.array(Image.open(DATA / 'pause.png').convert('RGB')), cv2.COLOR_RGB2GRAY)
        if np.std(expected) < 3 or float(cv2.matchTemplate(actual, expected, cv2.TM_CCOEFF_NORMED)[0, 0]) < .90:
            return False
        self.check_focus()
        u.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            time.sleep(.06)
        finally:
            u.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(.3)
        after = cv2.cvtColor(np.array(self.grab().crop((left, top, right, bottom))), cv2.COLOR_RGB2GRAY)
        return float(cv2.matchTemplate(after, expected, cv2.TM_CCOEFF_NORMED)[0, 0]) < .90

    def score(self, screenshot, key):
        game = np.array(screenshot.crop(self.cfg['rects']['game']))
        gray = cv2.cvtColor(game, cv2.COLOR_RGB2GRAY)
        template = self.templates[key]
        if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
            return 0
        if np.std(template) < 3:
            raise ValueError(f'{key} 範本過於單調，請重新框選')
        return float(cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1])

    def state(self, shot):
        scores = {key: self.score(shot, key) for key in TEMPLATES}
        if scores['status'] >= .95:
            return 'status'
        if scores['battle'] >= .95:
            if scores['victory'] >= .95:
                return 'victory'
            return 'menu' if scores['menu'] >= .95 else 'battle'
        if scores['map'] >= .95:
            return 'map'
        return 'unknown'

    def hp_once(self, shot, prefix):
        values = []
        for i, maximum in enumerate(self.cfg['maxima']):
            crop = shot.crop(self.cfg['rects'][f'{prefix}_hp{i}'])
            text, confidence = recognize_number(self.engine, crop)
            value = read_hp(text, confidence, maximum)
            values.append(value)
        return values

    def hp(self, prefix):
        first = self.hp_once(self.grab(), prefix)
        if self.stop_event.wait(.25):
            raise RuntimeError('已停止')
        second = self.hp_once(self.grab(), prefix)
        if first != second:
            raise ValueError('兩次兵力讀值不同，請檢查畫面或等待動畫結束')
        self.say('兵力：' + '、'.join(f'{n} {h}/{m}' for n, h, m in zip(NAMES, first, self.cfg['maxima'])))
        for n, h, m in zip(NAMES, first, self.cfg['maxima']):
            if h / m * 100 < self.cfg['threshold']:
                raise LowHP(f'低兵力停止：{n} {h}/{m}（{h/m:.0%}），請手動補血。')
        return first

    def worker(self):
        try:
            if self.stop_event.wait(self.cfg.get('start_delay', 5)):
                return
            self.target, title = self.active()
            self.check_focus()
            self.say('載入本機文字辨識模型……')
            if self.engine is None:
                self.engine = RapidOCR()
            self.check_focus()
            # Always check HP before beginning a new run.
            checked = False
            direction = 0x25
            unknown_since = None
            battle_since = None
            status_opening = False
            while not self.stop_event.is_set():
                shot = self.grab()
                state = self.state(shot)
                if state == 'unknown':
                    unknown_since = unknown_since or time.monotonic()
                    if time.monotonic() - unknown_since > 5:
                        raise RuntimeError('畫面超過 5 秒無法辨識，停止；可能移動、縮放或進入其他選單')
                    self.stop_event.wait(.4)
                    continue
                unknown_since = None
                if state == 'status':
                    self.hp('status')
                    checked = True
                    status_opening = False
                    self.press(0x58)
                elif state == 'map':
                    battle_since = None
                    if not checked:
                        if status_opening:
                            raise RuntimeError('按 V 後未出現兵力頁，停止')
                        self.press(0x56)
                        status_opening = True
                        self.stop_event.wait(.7)
                    else:
                        self.press(direction, .5)
                        direction = 0x27 if direction == 0x25 else 0x25
                elif state == 'menu':
                    battle_since = None
                    if not getattr(self, 'check_hp_after_battle', False):
                        self.hp('battle')
                    if getattr(self, 'direct_total_attack', False):
                        self.press(0x27)
                    elif self.score(self.grab(), 'selected') < .95:
                        self.press(0x27)
                        selected = False
                        for _ in range(8):
                            if self.stop_event.wait(.15):
                                raise RuntimeError('已停止')
                            if self.score(self.grab(), 'selected') >= .95:
                                selected = True
                                break
                        if not selected:
                            raise RuntimeError('無法確認總攻已選取，停止')
                    self.press(0x5A)
                    checked = False
                    self.stop_event.wait(.7)
                elif state == 'victory':
                    self.say('戰鬥獲勝，返回地圖後重新檢查兵力。')
                    self.press(0x5A)
                    checked = False
                    battle_since = None
                    self.stop_event.wait(.8)
                else:
                    if getattr(self, 'check_hp_after_battle', False):
                        self.stop_event.wait(.3)
                        continue
                    battle_since = battle_since or time.monotonic()
                    if time.monotonic() - battle_since > 45:
                        raise RuntimeError('戰鬥動畫超過 45 秒未回選單，停止')
                    # Monitor every stable readable animation frame; never press blindly.
                    try:
                        values = self.hp_once(shot, 'battle')
                        for n, h, m in zip(NAMES, values, self.cfg['maxima']):
                            if h / m * 100 < self.cfg['threshold']:
                                raise LowHP(f'低兵力停止：{n} {h}/{m}；請手動檢查兵力。')
                    except ValueError:
                        pass  # Animation can cover a digit; no new commands are issued here.
                    self.stop_event.wait(.3)
        except LowHP as e:
            if not getattr(self, 'auto_pause_on_stop', True):
                text = str(e) + ' 已停止送出按鍵。'
            else:
                try:
                    paused = self.pause_game()
                except Exception:
                    paused = False
                text = str(e) + (' 已點擊暫停，且按鈕圖示已變更；請確認遊戲已暫停。' if paused else ' 無法確認模擬器暫停，請立即手動按暫停。')
            self.say(text)
            self.events.put(('alert', text))
        except Exception as e:
            self.say(str(e))
            self.events.put(('alert', str(e)))
        finally:
            self.stop_event.set()
            self.events.put(('finished', None))

    def diagnose(self):
        if self.running or self.diagnosing:
            return
        try:
            self.validate()
        except Exception as e:
            return messagebox.showerror('設定未完成', str(e))
        self.say('3 秒後只讀取畫面，請切到遊戲。')
        self.diagnosing = True
        def run():
            try:
                time.sleep(3)
                self.target, _ = self.active()
                self.check_focus()
                if self.engine is None:
                    self.engine = RapidOCR()
                shot = self.grab()
                state = self.state(shot)
                self.say(f'辨識畫面：{state}')
                self.say('範本符合度：' + ', '.join(f'{k}={self.score(shot,k):.3f}' for k in TEMPLATES))
                if state in ['status', 'menu', 'battle']:
                    prefix = 'status' if state == 'status' else 'battle'
                    self.say('唯讀兵力：' + str(self.hp_once(shot, prefix)))
            except Exception as e:
                self.say('檢查失敗：' + str(e))
            finally:
                self.diagnosing = False
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        start_vk = getattr(self, 'start_vk', 0x77)
        stop_vk = getattr(self, 'stop_vk', 0x78)
        modifiers_ok = not getattr(self, 'require_ctrl_alt', False) or (u.GetAsyncKeyState(0x11) & 0x8000 and u.GetAsyncKeyState(0x12) & 0x8000)
        for vk in ([] if getattr(self, 'disable_hotkeys', False) else [start_vk, stop_vk]):
            down = bool(u.GetAsyncKeyState(vk) & 0x8001) and bool(modifiers_ok)
            if down and not self.hotkeys.get(vk):
                if vk == stop_vk or self.running:
                    self.stop('熱鍵停止')
                else:
                    self.start()
            self.hotkeys[vk] = down
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'log':
                self.status.set(value)
                self.log.configure(state='normal')
                self.log.insert('end', time.strftime('%H:%M:%S ') + value + '\n')
                self.log.see('end')
                self.log.configure(state='disabled')
            elif kind == 'alert':
                self.bell()
                self.status.set(value)
                if value.startswith('低兵力'):
                    messagebox.showwarning('兵力不足，已停止練功', value)
            elif kind == 'finished':
                self.running = False
            elif kind == 'maxima':
                for field, value in zip(self.maximum, value):
                    field.set(str(value))
        self.after(20, self.poll)

    def close(self):
        self.stop_event.set()
        self.destroy()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        app = App()
        app.withdraw()
        app.update_idletasks()
        engine = RapidOCR()
        Path(sys.argv[2]).write_text(json.dumps({'gui': 'ok', 'model': 'ok', 'python': sys.version}), 'utf-8')
        app.destroy()
    else:
        App().mainloop()
