"""Test what causes the StyledSteps crash."""
import sys, os, importlib.util
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Read the original source
with open(os.path.join(os.path.dirname(__file__), "..", "components", "styled_steps.py"), "r", encoding="utf-8") as f:
    src = f.read()

# ── Patch 1: remove _build_ui cleanup ───────────────────────────
old_cleanup = """    def _build_ui(self):
        # Remove old layout and its label widgets to prevent
        # "already has a layout" warnings on size/orientation changes.
        old = self.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            old.setParent(None)
            old.deleteLater()

        cfg = self._cfg()"""

new_no_cleanup = """    def _build_ui(self):
        cfg = self._cfg()"""

src_no_cleanup = src.replace(old_cleanup, new_no_cleanup)

# ── Patch 2: revert orientation setter to original ──────────────
old_orient = """        old_layout.setParent(None)
        old_layout.deleteLater()

        if self._orientation == "horizontal":
            self._layout = QHBoxLayout()
        else:
            self._layout = QVBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        for w in self._steps:
            w._orientation = self._orientation
            w._build_ui()
            self._layout.addWidget(w)
            w.update()
        self.setLayout(self._layout)"""

new_orient = """        old_layout.setParent(None)
        old_layout.deleteLater()

        if self._orientation == "horizontal":
            self._layout = QHBoxLayout(self)
        else:
            self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        for w in self._steps:
            w._orientation = self._orientation
            w._build_ui()
            self._layout.addWidget(w)
            w.update()"""

src_patched = src_no_cleanup.replace(old_orient, new_orient)

# ── Load patched module ─────────────────────────────────────────
import tempfile
patched_path = os.path.join(tempfile.gettempdir(), "styled_steps_patched.py")
with open(patched_path, "w", encoding="utf-8") as f:
    f.write(src_patched)

spec = importlib.util.spec_from_file_location("styled_steps_patched", patched_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
StyledSteps = mod.StyledSteps

# ── Test ────────────────────────────────────────────────────────
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
s = StyledSteps()
s.orientation = "vertical"
s.add_step("A", "desc")
s.add_step("B", "desc")
sys.stdout.write("Showing...\n"); sys.stdout.flush()
s.show()
sys.stdout.write("Processing events...\n"); sys.stdout.flush()
app.processEvents()
sys.stdout.write("SURVIVED! (original code)\n"); sys.stdout.flush()
