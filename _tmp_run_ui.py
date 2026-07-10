import sys
import os

log_path = os.path.join(os.path.dirname(__file__), "_tmp_ui_debug.log")

class Tee:
    def __init__(self, stdout, file):
        self.stdout = stdout
        self.file = file
    def write(self, data):
        self.stdout.write(data)
        self.file.write(data)
        self.file.flush()
    def flush(self):
        self.stdout.flush()
        self.file.flush()

f = open(log_path, "w", encoding="utf-8")
sys.stdout = Tee(sys.stdout, f)
sys.stderr = Tee(sys.stderr, f)

exec(open("freeassetfilter/ui/main_window.py").read())
