import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import virtuanes

app = object.__new__(virtuanes.NativeApp)
assert app.pause_game() is False
print("PASS: native pause disabled, no desktop input")
