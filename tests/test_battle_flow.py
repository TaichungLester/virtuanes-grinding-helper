import sys
from pathlib import Path
from types import SimpleNamespace
import queue
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
import bot
class Stop:
 def __init__(self): self.stopped=False
 def wait(self,*args): return self.stopped
 def is_set(self): return self.stopped
 def set(self): self.stopped=True
states=iter(['battle','menu','battle','menu','victory','victory','victory','map','status'])
keys=[]; checks=[]; messages=[]
def hp(prefix):
 checks.append(prefix)
 if prefix!='status': raise AssertionError('Battle HP must not be read')
 raise bot.LowHP('低兵力停止：第1位 40/100')
a=SimpleNamespace(cfg={'start_delay':0},stop_event=Stop(),engine=object(),
 active=lambda:(1,'VirtuaNES - 吞食天地'),check_focus=lambda:None,
 grab=lambda:None,state=lambda _:next(states),say=messages.append,
 hp=hp,hp_once=lambda *args: (_ for _ in ()).throw(AssertionError('Battle OCR called')),
 press=lambda key,*args:keys.append(key),pause_game=lambda: (_ for _ in ()).throw(AssertionError("Must never pause")),auto_pause_on_stop=False,
 direct_total_attack=True,check_hp_after_battle=True,events=queue.Queue())
bot.App.worker(a)
assert keys==[0x27,0x5a,0x27,0x5a,0x5a,0x5a,0x5a,0x56],keys
assert checks==['status'],checks
assert any('低兵力停止' in str(x) for x in messages),messages
print('PASS: continue through changing battle HP; right+A each menu; check low HP only after victory on map; no desktop input')
