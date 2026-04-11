"""
main.py
-------
Natív PyQt6 asztali alkalmazás – nincs böngésző, nincs Flask szerver.
Saját szövegszerkesztővel, fájlfeltöltéssel, hiányzó adat-dialógussal.

Indítás:
    python main.py
"""

import sys
import os
import re
from dotenv import load_dotenv

# .env betöltése az exe / script mellől
def _load_env():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(base, ".env"))

_load_env()

# UTF-8 mód kényszerítése
if not os.environ.get('PYTHONUTF8'):
    import subprocess
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    sys.exit(subprocess.run([sys.executable] + sys.argv, env=env).returncode)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QTextEdit, QFileDialog, QSpinBox,
    QProgressBar, QDialog, QLineEdit, QScrollArea,
    QDialogButtonBox, QToolBar, QStatusBar,
    QFrame, QSizePolicy, QMessageBox, QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import (
    QFont, QTextCharFormat,
    QAction
)

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Projektkönyvtár a Python path-ra
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ── Worker szálak ──────────────────────────────────────────────────────────

class TenderAnalyzerWorker(QThread):
    """Pályázati kiírás előzetes elemzése háttérszálban."""
    analysis_done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tender_text):
        super().__init__()
        self.tender_text = tender_text

    def run(self):
        try:
            from tender_analyzer import analyze_tender
            tender = analyze_tender(self.tender_text) or {}
            self.analysis_done.emit(tender)
        except Exception as e:
            self.error.emit(str(e))


class GeneratorWorker(QThread):
    """Szöveggenerálás háttérszálban."""
    progress = pyqtSignal(str, int)
    partial_text = pyqtSignal(str)
    finished = pyqtSignal(str, int)
    cancelled = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task, data, tender_text, style_text, max_rounds):
        super().__init__()
        self.task = task
        self.data = data
        self.tender_text = tender_text
        self.style_text = style_text
        self.max_rounds = max_rounds
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from orchestrator import run as orchestrator_run
            result = orchestrator_run(
                task=self.task,
                data=self.data,
                tender_text=self.tender_text or None,
                style_text=self.style_text or None,
                max_rounds=self.max_rounds,
                progress_callback=self._on_progress
            )
            if self._cancel:
                self.cancelled.emit()
                return
            text, score = result
            self.finished.emit(text, score)
        except Exception as e:
            if not self._cancel:
                self.error.emit(str(e))

    def _on_progress(self, msg, pct, partial=None):
        if self._cancel:
            raise InterruptedError("Generálás megszakítva.")
        self.progress.emit(msg, pct if pct is not None else -1)
        if partial:
            self.partial_text.emit(partial)


class CheckerWorker(QThread):
    """Ellenőrzőlista AI-alapú kiértékelése háttérszálban."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, szoveg, kovetelmenyek):
        super().__init__()
        self.szoveg = szoveg
        self.kovetelmenyek = kovetelmenyek

    def run(self):
        try:
            from checker import check_requirements
            result = check_requirements(self.szoveg, self.kovetelmenyek)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class RescorerWorker(QThread):
    """Újrapontozás háttérszálban – csak a reviewer fut le."""
    finished = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            from orchestrator import reviewer_prompt, parse_reviewer, llm
            chain = reviewer_prompt | llm
            response = chain.invoke({"text": self.text})
            score, feedback = parse_reviewer(response.content)
            self.finished.emit(score, feedback)
        except Exception as e:
            self.error.emit(str(e))


class RewriteWorker(QThread):
    """AI átírás háttérszálban."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, eredeti, utasitas, kontextus):
        super().__init__()
        self.eredeti = eredeti
        self.utasitas = utasitas
        self.kontextus = kontextus

    def run(self):
        try:
            from api_server import rewrite_text
            result = rewrite_text(self.eredeti, self.utasitas, self.kontextus)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ── Placeholder kitöltő dialógus (élő előnézettel) ────────────────────────

class PlaceholderFillDialog(QDialog):
    """Dialógus az AI által hagyott placeholder-ek kitöltéséhez, élő szöveg-előnézettel."""

    def __init__(self, text, placeholders_map, parent=None):
        """
        text: a teljes generált szöveg
        placeholders_map: {belső_kulcs: teljes_match} pl. {"DATUM_1": "[[DATUM_1]]"}
        """
        super().__init__(parent)
        self.setWindowTitle("Hiányzó adatok kitöltése")
        self.setMinimumSize(860, 620)
        self._base_text = text
        self._placeholders_map = placeholders_map
        self.fields = {}

        import html as _html
        self._html = _html

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Előnézet (felső rész) ──
        preview_wrap = QWidget()
        pw_layout = QVBoxLayout(preview_wrap)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(4)
        preview_lbl = QLabel("Szöveg előnézet – sárgán a hiányzó, zölden a már kitöltött helyek:")
        preview_lbl.setStyleSheet("color: #475569; font-size: 11px;")
        pw_layout.addWidget(preview_lbl)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet(
            "background: white; border: 1px solid #cbd5e1; border-radius:4px; font-size:13px;"
        )
        pw_layout.addWidget(self.preview)
        splitter.addWidget(preview_wrap)

        # ── Beviteli mezők (alsó rész) ──
        fields_wrap = QWidget()
        fw_layout = QVBoxLayout(fields_wrap)
        fw_layout.setContentsMargins(0, 4, 0, 0)
        fw_layout.setSpacing(4)
        fields_lbl = QLabel("Töltsd ki a hiányzó értékeket:")
        fields_lbl.setStyleSheet("color: #475569; font-size: 11px; font-weight: bold;")
        fw_layout.addWidget(fields_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        form = QVBoxLayout(inner)
        form.setSpacing(8)
        form.setContentsMargins(2, 2, 2, 2)

        for key, full_match in placeholders_map.items():
            row = QHBoxLayout()
            lbl = QLabel(f"{full_match}")
            lbl.setFixedWidth(160)
            lbl.setStyleSheet(
                "background:#fef08a; color:#92400e; font-weight:bold; "
                "padding:2px 6px; border-radius:3px;"
            )
            line = QLineEdit()
            line.setPlaceholderText("Írd be az értéket...")
            line.textChanged.connect(self._update_preview)
            self.fields[key] = line
            row.addWidget(lbl)
            row.addWidget(line)
            form.addLayout(row)

        form.addStretch()
        scroll.setWidget(inner)
        fw_layout.addWidget(scroll)
        splitter.addWidget(fields_wrap)

        splitter.setSizes([400, 200])
        layout.addWidget(splitter)

        btns = QDialogButtonBox()
        ok_btn = btns.addButton("Beillesztés", QDialogButtonBox.ButtonRole.AcceptRole)
        skip_btn = btns.addButton("Kihagyás (placeholder-ek bent maradnak)", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.setStyleSheet("background:#2563eb; color:white; padding:6px 14px; border-radius:4px;")
        skip_btn.setStyleSheet("padding:6px 14px; border-radius:4px;")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._update_preview()

    def _update_preview(self):
        h = self._html
        text = h.escape(self._base_text)

        for key, full_match in self._placeholders_map.items():
            val = self.fields[key].text().strip() if key in self.fields else ""
            escaped_match = h.escape(full_match)
            if val:
                repl = (
                    f'<span style="background:#bbf7d0; color:#166534; '
                    f'font-weight:bold;">{h.escape(val)}</span>'
                )
            else:
                repl = (
                    f'<span style="background:#fef08a; color:#92400e; '
                    f'font-weight:bold;">{escaped_match}</span>'
                )
            text = text.replace(escaped_match, repl)

        text = text.replace('\n', '<br>')
        self.preview.setHtml(
            f'<div style="font-family:Segoe UI,sans-serif; font-size:13px; '
            f'white-space:pre-wrap; line-height:1.6;">{text}</div>'
        )

    def get_values(self):
        return {k: v.text().strip() for k, v in self.fields.items() if v.text().strip()}


# ── Hiányzó adatok dialógus ────────────────────────────────────────────────

class MissingDataDialog(QDialog):
    """Felugró ablak a hiányzó adatok bekéréséhez (generálás előtt)."""

    def __init__(self, missing_fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hiányzó adatok")
        self.setMinimumWidth(480)
        self.fields = {}

        layout = QVBoxLayout(self)

        info = QLabel(
            "A pályázati kiírás elemzése során az alábbi adatok hiányoznak.\n"
            "Kérlek töltsd ki őket, vagy kattints a 'Kihagyás' gombra."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; margin-bottom: 8px;")
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        form = QVBoxLayout(inner)
        form.setSpacing(12)
        form.setContentsMargins(4, 4, 4, 4)

        for field in missing_fields:
            field_widget = QWidget()
            field_layout = QVBoxLayout(field_widget)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(3)
            label = QLabel(field)
            label.setWordWrap(True)
            label.setStyleSheet("color: #334155; font-weight: bold;")
            line = QLineEdit()
            line.setPlaceholderText("Írd be az adatot...")
            self.fields[field] = line
            field_layout.addWidget(label)
            field_layout.addWidget(line)
            form.addWidget(field_widget)

        form.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        btns = QDialogButtonBox()
        ok_btn = btns.addButton("Tovább a generáláshoz", QDialogButtonBox.ButtonRole.AcceptRole)
        skip_btn = btns.addButton("Kihagyás", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.setStyleSheet("background:#2563eb; color:white; padding:6px 14px; border-radius:4px;")
        skip_btn.setStyleSheet("padding:6px 14px; border-radius:4px;")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self):
        """Visszaadja a kitöltött mezőket dict-ként."""
        return {k: v.text().strip() for k, v in self.fields.items() if v.text().strip()}


# ── Főablak ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Pályázatíró")
        self.showMaximized()

        # Belső állapot
        self._regi_path = None
        self._kiiras_path = None
        self._ceg_path = None
        self._tender_text = ""
        self._style_text = ""
        self._rewrite_result = ""
        self._generator_worker = None
        self._analyzer_worker = None
        self._rewrite_worker = None
        self._file_loaders = set()
        self._tender_info = {}
        self._versions = []   # [(text, score), ...]
        self._version_idx = -1

        # Piszkozat fájl elérési útja (exe / script mellé)
        if getattr(sys, 'frozen', False):
            _base = os.path.dirname(sys.executable)
        else:
            _base = os.path.dirname(os.path.abspath(__file__))
        self._draft_path = os.path.join(_base, "draft.txt")
        self._session_path = os.path.join(_base, "session.json")

        self._build_ui()
        self._apply_style()
        self._restore_draft()
        self._restore_session()

        # Auto-mentés 30 másodpercenként
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(30_000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 1280) // 2
        y = (screen.height() - 820) // 2
        self.move(x, y)

    # ── UI felépítés ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        root.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([340, 940])

        # Állapotsor
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(300)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("Kész.")

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Cím
        title = QLabel("AI Pályázatíró")
        title.setObjectName("appTitle")
        layout.addWidget(title)

        sep = self._hsep()
        layout.addWidget(sep)

        # Fájlok szekció
        layout.addWidget(self._section_label("Fájlok"))

        self.btn_regi = self._file_button("Régi pályázatok (stílustanulás)")
        self.btn_regi.clicked.connect(lambda: self._pick_file("regi"))
        layout.addWidget(self.btn_regi)

        self.btn_kiiras = self._file_button("Pályázati kiírás")
        self.btn_kiiras.clicked.connect(lambda: self._pick_file("kiiras"))
        layout.addWidget(self.btn_kiiras)

        self.btn_ceg = self._file_button("Cégadatlap (PDF/DOCX)")
        self.btn_ceg.clicked.connect(lambda: self._pick_file("ceg"))
        layout.addWidget(self.btn_ceg)

        layout.addWidget(self._hsep())

        # Feladat
        layout.addWidget(self._section_label("Feladat leírása"))
        self.task_edit = QPlainTextEdit()
        self.task_edit.setPlaceholderText(
            "Pl: Írj bevezető fejezetet egy digitális fejlesztési pályázathoz"
        )
        self.task_edit.setFixedHeight(90)
        layout.addWidget(self.task_edit)

        # Cégadatok szöveg
        ceg_header = QHBoxLayout()
        ceg_header.addWidget(self._section_label("Cégadatok (szöveg)"))
        ceg_header.addStretch()
        ceg_popup_btn = QPushButton("⤢")
        ceg_popup_btn.setToolTip("Nagyobb ablakban szerkesztés")
        ceg_popup_btn.setFixedSize(22, 22)
        ceg_popup_btn.setStyleSheet(
            "border: 1px solid #cbd5e1; border-radius: 3px; "
            "background: #f1f5f9; color: #475569; font-size: 12px;"
        )
        ceg_popup_btn.clicked.connect(self._on_data_popup)
        ceg_header.addWidget(ceg_popup_btn)
        layout.addLayout(ceg_header)
        self.data_edit = QPlainTextEdit()
        self.data_edit.setPlaceholderText(
            "Cég neve: Példa Kft.\nProjekt költsége: 5 000 000 Ft\n..."
        )
        self.data_edit.setFixedHeight(110)
        layout.addWidget(self.data_edit)

        layout.addWidget(self._hsep())

        # Körök száma
        rounds_row = QHBoxLayout()
        rounds_row.addWidget(QLabel("Javítási körök:"))
        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(1, 5)
        self.rounds_spin.setValue(2)
        self.rounds_spin.setFixedWidth(90)
        rounds_row.addWidget(self.rounds_spin)
        rounds_row.addStretch()
        layout.addLayout(rounds_row)

        # Generálás + Mégse gombok
        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        self.gen_btn = QPushButton("  Generálás")
        self.gen_btn.setObjectName("genBtn")
        self.gen_btn.setFixedHeight(42)
        self.gen_btn.clicked.connect(self._on_generate)
        gen_row.addWidget(self.gen_btn, stretch=1)

        self.cancel_btn = QPushButton("Mégse")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setFixedHeight(42)
        self.cancel_btn.setFixedWidth(70)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        gen_row.addWidget(self.cancel_btn)
        layout.addLayout(gen_row)

        # Bal panel törlő gomb
        reset_btn = QPushButton("Mezők törlése")
        reset_btn.setObjectName("resetBtn")
        reset_btn.setFixedHeight(32)
        reset_btn.clicked.connect(self._on_reset_left)
        layout.addWidget(reset_btn)

        layout.addStretch()
        return panel

    def _build_right_panel(self):
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Fejléc sor: pontszám + Word export
        header = QHBoxLayout()
        self.score_label = QLabel("Pontszám: –")
        self.score_label.setObjectName("scoreLabel")
        header.addWidget(self.score_label)

        self.prev_btn = QPushButton("←")
        self.prev_btn.setObjectName("navBtn")
        self.prev_btn.setFixedWidth(28)
        self.prev_btn.setToolTip("Előző verzió")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._on_prev_version)
        header.addWidget(self.prev_btn)

        self.version_label = QLabel("")
        self.version_label.setStyleSheet("color: #64748b; font-size: 11px; min-width: 30px; text-align: center;")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.version_label)

        self.next_btn = QPushButton("→")
        self.next_btn.setObjectName("navBtn")
        self.next_btn.setFixedWidth(28)
        self.next_btn.setToolTip("Következő verzió")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_version)
        header.addWidget(self.next_btn)

        self.rescore_btn = QPushButton("Újrapontozás")
        self.rescore_btn.setObjectName("rescoreBtn")
        self.rescore_btn.clicked.connect(self._on_rescore)
        header.addWidget(self.rescore_btn)
        header.addStretch()
        clear_btn = QPushButton("Törlés")
        clear_btn.setObjectName("clearBtn")
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)
        export_btn = QPushButton("Word export (.docx)")
        export_btn.setObjectName("exportBtn")
        export_btn.clicked.connect(self._export_word)
        header.addWidget(export_btn)
        layout.addLayout(header)

        # Formázási toolbar
        fmt_bar = QToolBar()
        fmt_bar.setIconSize(QSize(16, 16))
        fmt_bar.setMovable(False)
        fmt_bar.setStyleSheet("QToolBar { border: none; background: transparent; spacing: 2px; }")

        self._font_size_box = QComboBox()
        self._font_size_box.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32"])
        self._font_size_box.setCurrentText("11")
        self._font_size_box.setFixedWidth(75)
        self._font_size_box.setEditable(True)
        self._font_size_box.setToolTip("Betűméret")
        self._font_size_box.lineEdit().setStyleSheet("padding-left: 6px;")
        self._font_size_box.currentTextChanged.connect(self._on_font_size_changed)
        fmt_bar.addWidget(self._font_size_box)
        fmt_bar.addSeparator()

        self._act_bold = QAction("B", self)
        self._act_bold.setCheckable(True)
        self._act_bold.setToolTip("Félkövér (Ctrl+B)")
        self._act_bold.setShortcut("Ctrl+B")
        self._act_bold.triggered.connect(self._toggle_bold)
        fmt_bar.addAction(self._act_bold)

        self._act_italic = QAction("I", self)
        self._act_italic.setCheckable(True)
        self._act_italic.setToolTip("Dőlt (Ctrl+I)")
        self._act_italic.setShortcut("Ctrl+I")
        self._act_italic.triggered.connect(self._toggle_italic)
        fmt_bar.addAction(self._act_italic)

        self._act_underline = QAction("U", self)
        self._act_underline.setCheckable(True)
        self._act_underline.setToolTip("Aláhúzott (Ctrl+U)")
        self._act_underline.setShortcut("Ctrl+U")
        self._act_underline.triggered.connect(self._toggle_underline)
        fmt_bar.addAction(self._act_underline)

        fmt_bar.addSeparator()

        act_h1 = QAction("H1", self)
        act_h1.setToolTip("Főcím")
        act_h1.triggered.connect(lambda: self._apply_heading(1))
        fmt_bar.addAction(act_h1)

        act_h2 = QAction("H2", self)
        act_h2.setToolTip("Alcím")
        act_h2.triggered.connect(lambda: self._apply_heading(2))
        fmt_bar.addAction(act_h2)

        act_normal = QAction("Normál", self)
        act_normal.setToolTip("Normál bekezdés")
        act_normal.triggered.connect(self._apply_normal)
        fmt_bar.addAction(act_normal)

        fmt_bar.addSeparator()

        act_beautify = QAction("✨ Szépítés", self)
        act_beautify.setToolTip("Markdown jelölések (##, **, * stb.) átalakítása valódi formázássá")
        act_beautify.triggered.connect(self._on_beautify)
        fmt_bar.addAction(act_beautify)

        self._act_undo_beautify = QAction("↩ Visszavonás", self)
        self._act_undo_beautify.setToolTip("Szépítés előtti szöveg visszaállítása")
        self._act_undo_beautify.triggered.connect(self._on_undo_beautify)
        self._act_undo_beautify.setEnabled(False)
        fmt_bar.addAction(self._act_undo_beautify)

        layout.addWidget(fmt_bar)

        # Fő szövegszerkesztő
        self.editor = QTextEdit()
        self.editor.setObjectName("mainEditor")
        self.editor.setPlaceholderText(
            "A generált pályázati szöveg itt jelenik meg. "
            "Közvetlenül szerkesztheted, vagy használd az AI átírás funkciót lent."
        )
        self.editor.cursorPositionChanged.connect(self._update_format_buttons)
        layout.addWidget(self.editor, stretch=1)

        # Ellenőrzőlista panel (generálás után jelenik meg)
        self.checklist_frame = QFrame()
        self.checklist_frame.setObjectName("checklistFrame")
        self.checklist_frame.setVisible(False)
        checklist_outer = QVBoxLayout(self.checklist_frame)
        checklist_outer.setContentsMargins(10, 6, 10, 6)
        checklist_outer.setSpacing(4)

        checklist_header = QHBoxLayout()
        checklist_title = QLabel("Ellenőrzőlista – pályázati kiírás alapján")
        checklist_title.setObjectName("sectionLabel")
        checklist_header.addWidget(checklist_title)
        checklist_header.addStretch()
        self.check_btn = QPushButton("🔍 Ellenőrzés")
        self.check_btn.setObjectName("checkBtn")
        self.check_btn.setToolTip("AI megvizsgálja hogy a szöveg teljesíti-e a követelményeket")
        self.check_btn.clicked.connect(self._on_check_requirements)
        checklist_header.addWidget(self.check_btn)
        self.checklist_toggle_btn = QPushButton("▼ Részletek")
        self.checklist_toggle_btn.setFlat(True)
        self.checklist_toggle_btn.setStyleSheet(
            "color: #2563eb; font-size: 11px; border: none; padding: 0;"
        )
        self.checklist_toggle_btn.clicked.connect(self._toggle_checklist)
        checklist_header.addWidget(self.checklist_toggle_btn)
        checklist_outer.addLayout(checklist_header)

        checklist_scroll = QScrollArea()
        checklist_scroll.setWidgetResizable(True)
        checklist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        checklist_scroll.setMaximumHeight(160)
        checklist_scroll.setVisible(False)
        self.checklist_body = QWidget()
        self.checklist_body_layout = QVBoxLayout(self.checklist_body)
        self.checklist_body_layout.setContentsMargins(0, 4, 0, 0)
        self.checklist_body_layout.setSpacing(4)
        checklist_scroll.setWidget(self.checklist_body)
        self._checklist_scroll = checklist_scroll
        checklist_outer.addWidget(checklist_scroll)

        layout.addWidget(self.checklist_frame)

        # AI átírás panel
        rewrite_frame = QFrame()
        rewrite_frame.setObjectName("rewriteFrame")
        rewrite_layout = QVBoxLayout(rewrite_frame)
        rewrite_layout.setContentsMargins(10, 8, 10, 8)
        rewrite_layout.setSpacing(6)

        rewrite_title = QLabel("AI átírás")
        rewrite_title.setObjectName("sectionLabel")
        rewrite_layout.addWidget(rewrite_title)

        row1 = QHBoxLayout()
        self.selected_edit = QPlainTextEdit()
        self.selected_edit.setPlaceholderText("Jelöld ki a szövegben az átírandó részt, majd kattints a 'Kijelölés átvétele' gombra")
        self.selected_edit.setFixedHeight(60)
        row1.addWidget(self.selected_edit, stretch=3)

        copy_sel_btn = QPushButton("Kijelölés\nátvétele")
        copy_sel_btn.setFixedWidth(100)
        copy_sel_btn.clicked.connect(self._copy_selection)
        row1.addWidget(copy_sel_btn)
        rewrite_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.instruction_edit = QLineEdit()
        self.instruction_edit.setPlaceholderText("Utasítás: pl. Rövidítsd le, legyen formálisabb...")
        row2.addWidget(self.instruction_edit, stretch=3)

        self.rewrite_btn = QPushButton("Átírás")
        self.rewrite_btn.setObjectName("rewriteBtn")
        self.rewrite_btn.setFixedWidth(80)
        self.rewrite_btn.clicked.connect(self._on_rewrite)
        row2.addWidget(self.rewrite_btn)

        insert_btn = QPushButton("Beillesztés")
        insert_btn.setFixedWidth(90)
        insert_btn.clicked.connect(self._insert_rewrite)
        row2.addWidget(insert_btn)
        rewrite_layout.addLayout(row2)

        self.rewrite_result = QPlainTextEdit()
        self.rewrite_result.setPlaceholderText("Az átírt szöveg itt jelenik meg...")
        self.rewrite_result.setFixedHeight(60)
        self.rewrite_result.setReadOnly(True)
        rewrite_layout.addWidget(self.rewrite_result)

        layout.addWidget(rewrite_frame)
        return panel

    # ── Segéd widgetek ────────────────────────────────────────────────────

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionLabel")
        return lbl

    def _file_button(self, text):
        btn = QPushButton(f"  {text}")
        btn.setObjectName("fileBtn")
        btn.setFixedHeight(34)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return btn

    def _hsep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("color: #e2e8f0;")
        return sep

    # ── Fájlkezelés ──────────────────────────────────────────────────────

    def _pick_file(self, kind):
        path, _ = QFileDialog.getOpenFileName(
            self, "Fájl kiválasztása", "",
            "Dokumentumok (*.pdf *.docx *.doc)"
        )
        if not path:
            return

        fname = os.path.basename(path)
        if kind == "regi":
            self._regi_path = path
            self.btn_regi.setText(f"  {fname}")
            self._load_text_async(path, "style")
        elif kind == "kiiras":
            self._kiiras_path = path
            self._tender_text = ""  # azonnal töröljük, nehogy a régi session felülírja
            self.btn_kiiras.setText(f"  {fname}")
            self._load_text_async(path, "tender")
        elif kind == "ceg":
            self._ceg_path = path
            self.btn_ceg.setText(f"  {fname}")
            self._load_text_async(path, "data")

    def _load_text_async(self, path, role):
        """Fájl beolvasása háttérszálban, eredmény az adott role-ba."""
        from file_reader import read_file

        class FileLoader(QThread):
            done = pyqtSignal(str, str)
            err = pyqtSignal(str)
            def __init__(self, p, r):
                super().__init__()
                self.p, self.r = p, r
            def run(self):
                try:
                    txt = read_file(self.p) or ""
                    self.done.emit(txt, self.r)
                except Exception as e:
                    self.err.emit(str(e))

        loader = FileLoader(path, role)
        loader.done.connect(self._on_file_loaded)
        loader.done.connect(lambda t, r, l=loader: self._file_loaders.discard(l))
        loader.err.connect(lambda e: self.status_bar.showMessage(f"Hiba: {e}"))
        loader.start()
        self._file_loaders.add(loader)  # listában tartjuk, nem írjuk felül
        self.status_bar.showMessage(f"Fájl beolvasása: {os.path.basename(path)}...")

    def _on_file_loaded(self, text, role):
        if role == "tender":
            self._tender_text = text
            self.status_bar.showMessage("Pályázati kiírás betöltve.")
        elif role == "style":
            self._style_text = text
            self.status_bar.showMessage("Régi pályázat betöltve (stílusminta).")
        elif role == "data":
            self._tender_text_ceg = text
            if not self.data_edit.toPlainText().strip():
                self.data_edit.setPlainText(text)
            self.status_bar.showMessage("Cégadatlap betöltve.")

    # ── Generálás ────────────────────────────────────────────────────────

    def _on_generate(self):
        task = self.task_edit.toPlainText().strip()
        data = self.data_edit.toPlainText().strip()

        if not task:
            QMessageBox.warning(self, "Hiányzó adat", "Kérlek add meg a feladat leírását!")
            return
        if not data:
            QMessageBox.warning(self, "Hiányzó adat", "Kérlek add meg a cégadatokat!")
            return

        if self._tender_text:
            # Először elemezzük ki a hiányzó adatokat
            self._start_pre_analysis(task, data)
        else:
            self._start_generation(task, data)

    def _start_pre_analysis(self, task, data):
        self._set_busy(True, "Pályázati kiírás elemzése...")
        self._pending_task = task
        self._pending_data = data

        self._analyzer_worker = TenderAnalyzerWorker(self._tender_text)
        self._analyzer_worker.analysis_done.connect(self._on_analysis_done)
        self._analyzer_worker.error.connect(self._on_error)
        self._analyzer_worker.start()

    def _on_analysis_done(self, tender):
        task = self._pending_task
        data = self._pending_data

        self._tender_info = tender  # eltároljuk a generálás utáni ellenőrzőlistához

        missing_fields = tender.get('hianyzó_adatok', [])
        if missing_fields:
            dlg = MissingDataDialog(missing_fields, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                values = dlg.get_values()
                if values:
                    extra = "\n\nFelhasználó által megadott hiányzó adatok:\n"
                    extra += "\n".join(f"- {k}: {v}" for k, v in values.items())
                    data = data + extra

        self._start_generation(task, data)

    def _start_generation(self, task, data):
        self._set_busy(True, "Szöveg generálása...")
        self._generator_worker = GeneratorWorker(
            task=task,
            data=data,
            tender_text=self._tender_text,
            style_text=self._style_text,
            max_rounds=self.rounds_spin.value()
        )
        self._generator_worker.progress.connect(self._on_progress)
        self._generator_worker.partial_text.connect(self._on_partial_text)
        self._generator_worker.finished.connect(self._on_generation_done)
        self._generator_worker.cancelled.connect(self._on_cancelled)
        self._generator_worker.error.connect(self._on_error)
        self._generator_worker.start()

    def _on_progress(self, msg, pct):
        self.status_bar.showMessage(msg)
        if pct >= 0:
            self.progress_bar.setValue(pct)

    def _on_partial_text(self, text):
        """Közbenső szöveg megjelenítése szürkén – jelzi hogy még folyamatban van."""
        self.editor.setPlainText(text)
        self.editor.setStyleSheet(
            "#mainEditor { background: white; border: 1px solid #cbd5e1; "
            "border-radius: 6px; font-size: 13px; padding: 8px; color: #94a3b8; }"
        )

    def _on_generation_done(self, text, score):
        self._set_busy(False)
        self.editor.setStyleSheet("")
        if text:
            text = self._fill_placeholders(text)
            self._versions.append((text, score))
            self._version_idx = len(self._versions) - 1
            self._show_version(self._version_idx)
            self._update_checklist()
        else:
            QMessageBox.critical(self, "Hiba", "Nem sikerült szöveget generálni. Próbáld újra!")
            self.status_bar.showMessage("Generálás sikertelen.")

    def _show_version(self, idx):
        text, score = self._versions[idx]
        self.editor.setPlainText(text)
        self._update_score(score)
        total = len(self._versions)
        self.version_label.setText(f"{idx + 1}/{total}")
        self.prev_btn.setEnabled(idx > 0)
        self.next_btn.setEnabled(idx < total - 1)
        self.status_bar.showMessage(f"Verzió: {idx + 1}/{total} | Pontszám: {score}/100")

    def _on_prev_version(self):
        if self._version_idx > 0:
            self._version_idx -= 1
            self._show_version(self._version_idx)

    def _on_next_version(self):
        if self._version_idx < len(self._versions) - 1:
            self._version_idx += 1
            self._show_version(self._version_idx)

    def _update_checklist(self):
        """Feltölti és megmutatja az ellenőrzőlistát a tender elemzés alapján."""
        tender = self._tender_info
        if not tender:
            return

        # Töröljük az előző tartalmat
        while self.checklist_body_layout.count():
            item = self.checklist_body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sections = [
            ("Kötelező fejezetek", tender.get('kotelezo_fejezetek', []), "#2563eb"),
            ("Fontos követelmények", tender.get('fontos_kovetelmenyek', []), "#dc2626"),
            ("Értékelési szempontok", tender.get('ertékelesi_szempontok', []), "#d97706"),
            ("Kötelező dokumentumok", tender.get('kotelezo_dokumentumok', []), "#7c3aed"),
        ]

        meta_parts = []
        if tender.get('beadasi_hatarid'):
            meta_parts.append(f"Határidő: {tender['beadasi_hatarid']}")
        if tender.get('max_tamogatas'):
            meta_parts.append(f"Max támogatás: {tender['max_tamogatas']}")
        if tender.get('tamogatas_arany'):
            meta_parts.append(f"Intenzitás: {tender['tamogatas_arany']}")
        if meta_parts:
            meta_lbl = QLabel("  •  ".join(meta_parts))
            meta_lbl.setStyleSheet("color: #475569; font-size: 11px;")
            meta_lbl.setWordWrap(True)
            self.checklist_body_layout.addWidget(meta_lbl)

        for title, items, color in sections:
            if not items:
                continue
            sec_lbl = QLabel(title)
            sec_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 11px; margin-top: 4px;"
            )
            self.checklist_body_layout.addWidget(sec_lbl)
            for item in items:
                row = QCheckBox(item)
                row.setStyleSheet(self._checkbox_style(False))
                row.stateChanged.connect(lambda state, cb=row: cb.setStyleSheet(
                    self._checkbox_style(state == 2)
                ))
                self.checklist_body_layout.addWidget(row)

        self.checklist_frame.setVisible(True)
        self._checklist_scroll.setVisible(True)
        self.checklist_toggle_btn.setText("▲ Elrejt")

    def _checkbox_style(self, checked: bool) -> str:
        color = "#16a34a" if checked else "#dc2626"
        return (
            f"QCheckBox {{ color: {color}; font-size: 12px; padding: 2px 4px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #94a3b8; "
            f"border-radius: 3px; background: white; }}"
            f"QCheckBox::indicator:checked {{ background: #16a34a; border-color: #16a34a; }}"
        )

    def _toggle_checklist(self):
        visible = self._checklist_scroll.isVisible()
        self._checklist_scroll.setVisible(not visible)
        self.checklist_toggle_btn.setText("▼ Részletek" if visible else "▲ Elrejt")

    def _on_check_requirements(self):
        szoveg = self.editor.toPlainText().strip()
        if not szoveg:
            QMessageBox.warning(self, "Üres szöveg", "Nincs szöveg az ellenőrzéshez!")
            return
        if not self._tender_info:
            QMessageBox.warning(self, "Nincs elemzés", "Nincs betöltött pályázati kiírás!")
            return

        # Összes ellenőrizhető elem összegyűjtése
        tender = self._tender_info
        kovetelmenyek = (
            tender.get('kotelezo_fejezetek', []) +
            tender.get('fontos_kovetelmenyek', []) +
            tender.get('ertékelesi_szempontok', []) +
            tender.get('kotelezo_dokumentumok', [])
        )
        if not kovetelmenyek:
            QMessageBox.information(self, "Nincs követelmény", "Nem találtam ellenőrizhető követelményt.")
            return

        self.check_btn.setEnabled(False)
        self.check_btn.setText("⏳ Ellenőrzés...")
        self.status_bar.showMessage("Követelmények ellenőrzése folyamatban...")

        self._checker_worker = CheckerWorker(szoveg, kovetelmenyek)
        self._checker_worker.finished.connect(self._on_check_done)
        self._checker_worker.error.connect(self._on_check_error)
        self._checker_worker.start()

    def _on_check_done(self, result):
        self.check_btn.setEnabled(True)
        self.check_btn.setText("🔍 Ellenőrzés")
        teljesitett = set(result.get("teljesitett", []))
        hianyzik = set(result.get("hianyzik", []))

        # Végigmegyünk a checkboxokon és beállítjuk az állapotukat
        for i in range(self.checklist_body_layout.count()):
            widget = self.checklist_body_layout.itemAt(i).widget()
            if isinstance(widget, QCheckBox):
                szoveg = widget.text()
                if any(t.lower() in szoveg.lower() or szoveg.lower() in t.lower()
                       for t in teljesitett):
                    widget.setChecked(True)
                elif any(h.lower() in szoveg.lower() or szoveg.lower() in h.lower()
                         for h in hianyzik):
                    widget.setChecked(False)

        # Nyissuk ki a listát ha be volt csukva
        self._checklist_scroll.setVisible(True)
        self.checklist_toggle_btn.setText("▲ Elrejt")

        osszes = len(teljesitett) + len(hianyzik)
        self.status_bar.showMessage(
            f"Ellenőrzés kész: {len(teljesitett)}/{osszes} követelmény teljesül."
        )

    def _on_check_error(self, msg):
        self.check_btn.setEnabled(True)
        self.check_btn.setText("🔍 Ellenőrzés")
        QMessageBox.critical(self, "Hiba", f"Ellenőrzés sikertelen:\n{msg}")

    def _fill_placeholders(self, text):
        """Megkeresi az AI által hagyott [PLACEHOLDER] és [[PLACEHOLDER]] jelöléseket és bekéri az értékeket."""
        pattern = re.compile(r'\[\[([^\[\]\n]{1,60})\]\]|\[([^\[\]\n]{1,60})\]')

        seen = {}
        for m in pattern.finditer(text):
            inner = m.group(1) or m.group(2)
            full = m.group(0)
            if inner not in seen:
                seen[inner] = full  # {belső_kulcs: teljes_match}

        if not seen:
            return text

        dlg = PlaceholderFillDialog(text, seen, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            values = dlg.get_values()
            for key, val in values.items():
                text = text.replace(seen[key], val)
        return text

    def _on_rescore(self):
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Üres szöveg", "Nincs szöveg a pontozáshoz!")
            return
        self.rescore_btn.setEnabled(False)
        self.rescore_btn.setText("Pontozás...")
        self.status_bar.showMessage("Újrapontozás folyamatban...")
        self._rescorer_worker = RescorerWorker(text)
        self._rescorer_worker.finished.connect(self._on_rescore_done)
        self._rescorer_worker.error.connect(self._on_rescore_error)
        self._rescorer_worker.start()

    def _on_rescore_done(self, score, feedback):
        self._update_score(score)
        self.rescore_btn.setEnabled(True)
        self.rescore_btn.setText("Újrapontozás")
        self.status_bar.showMessage(f"Újrapontozás kész: {score}/100")

        if score >= 85:
            ikon = "✅"
        elif score >= 70:
            ikon = "⚠️"
        else:
            ikon = "❌"

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Pontozás eredménye")
        dlg.setText(f"{ikon}  <b>Pontszám: {score}/100</b>")
        dlg.setInformativeText(feedback)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()

    def _on_rescore_error(self, msg):
        self.rescore_btn.setEnabled(True)
        self.rescore_btn.setText("Újrapontozás")
        QMessageBox.critical(self, "Hiba", f"Pontozás sikertelen:\n{msg}")
        self.status_bar.showMessage("Újrapontozás sikertelen.")

    def _on_cancelled(self):
        self._set_busy(False)
        self.cancel_btn.setEnabled(True)
        self.status_bar.showMessage("Generálás megszakítva.")

    def _on_error(self, msg):
        self._set_busy(False)
        self.cancel_btn.setEnabled(True)
        QMessageBox.critical(self, "Hiba", f"Hiba történt:\n{msg}")
        self.status_bar.showMessage(f"Hiba: {msg}")

    def _update_score(self, score):
        if score >= 85:
            color = "#16a34a"
            emoji = "✅"
        elif score >= 70:
            color = "#d97706"
            emoji = "⚠️"
        else:
            color = "#dc2626"
            emoji = "❌"
        self.score_label.setText(f"Pontszám: {score}/100 {emoji}")
        self.score_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")

    def _set_busy(self, busy, msg=""):
        self.gen_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setValue(0)
            self.status_bar.showMessage(msg)
        else:
            self.progress_bar.setValue(100)

    def _on_cancel(self):
        if self._generator_worker and self._generator_worker.isRunning():
            self._generator_worker.cancel()
            self._generator_worker.terminate()
            self._generator_worker.wait(2000)
            self._set_busy(False)
            self.cancel_btn.setEnabled(True)
            self.status_bar.showMessage("Generálás megszakítva.")

    # ── Szövegformázás ────────────────────────────────────────────────────

    def _toggle_bold(self):
        fmt = QTextCharFormat()
        cursor = self.editor.textCursor()
        current = cursor.charFormat().fontWeight()
        fmt.setFontWeight(
            QFont.Weight.Normal if current == QFont.Weight.Bold else QFont.Weight.Bold
        )
        cursor.mergeCharFormat(fmt)

    def _toggle_italic(self):
        fmt = QTextCharFormat()
        cursor = self.editor.textCursor()
        fmt.setFontItalic(not cursor.charFormat().fontItalic())
        cursor.mergeCharFormat(fmt)

    def _toggle_underline(self):
        fmt = QTextCharFormat()
        cursor = self.editor.textCursor()
        fmt.setFontUnderline(not cursor.charFormat().fontUnderline())
        cursor.mergeCharFormat(fmt)

    def _apply_heading(self, level):
        cursor = self.editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(18 if level == 1 else 14)
        fmt.setFontWeight(QFont.Weight.Bold)
        cursor.mergeCharFormat(fmt)

    def _apply_normal(self):
        cursor = self.editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(11)
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def _on_beautify(self):
        plain = self.editor.toPlainText().strip()
        if not plain:
            return
        self._before_beautify = self.editor.toPlainText()
        self._is_beautified = True
        from text_beautifier import beautify_to_html
        html = beautify_to_html(plain)
        self.editor.setHtml(html)
        self._act_undo_beautify.setEnabled(True)
        self.status_bar.showMessage("Szépítés kész – markdown jelölések formázássá alakítva.")

    def _on_undo_beautify(self):
        if hasattr(self, '_before_beautify') and self._before_beautify:
            self.editor.setPlainText(self._before_beautify)
            self._before_beautify = ""
            self._is_beautified = False
            self._act_undo_beautify.setEnabled(False)
            self.status_bar.showMessage("Szépítés visszavonva.")

    def _update_format_buttons(self):
        cursor = self.editor.textCursor()
        fmt = cursor.charFormat()
        self._act_bold.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self._act_italic.setChecked(fmt.fontItalic())
        self._act_underline.setChecked(fmt.fontUnderline())
        size = fmt.fontPointSize()
        if size > 0:
            self._font_size_box.blockSignals(True)
            self._font_size_box.setCurrentText(str(int(size)))
            self._font_size_box.blockSignals(False)

    def _on_font_size_changed(self, value):
        try:
            size = int(value)
        except ValueError:
            return
        if size <= 0:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.editor.textCursor().mergeCharFormat(fmt)

    # ── AI átírás ─────────────────────────────────────────────────────────

    def _copy_selection(self):
        cursor = self.editor.textCursor()
        selected = cursor.selectedText()
        if selected:
            self.selected_edit.setPlainText(selected)
        else:
            self.status_bar.showMessage("Nincs kijelölt szöveg a szerkesztőben.")

    def _on_rewrite(self):
        eredeti = self.selected_edit.toPlainText().strip()
        utasitas = self.instruction_edit.text().strip()
        if not eredeti:
            QMessageBox.warning(self, "Hiányzó adat", "Nincs kijelölt szövegrész az átíráshoz!")
            return
        if not utasitas:
            QMessageBox.warning(self, "Hiányzó adat", "Add meg az átírási utasítást!")
            return

        kontextus = self.editor.toPlainText()[:1000]
        self.rewrite_btn.setEnabled(False)
        self.status_bar.showMessage("AI átírás folyamatban...")

        self._rewrite_worker = RewriteWorker(eredeti, utasitas, kontextus)
        self._rewrite_worker.finished.connect(self._on_rewrite_done)
        self._rewrite_worker.error.connect(self._on_rewrite_error)
        self._rewrite_worker.start()

    def _on_rewrite_done(self, text):
        self._rewrite_result = text
        self.rewrite_result.setPlainText(text)
        self.rewrite_btn.setEnabled(True)
        self.status_bar.showMessage("Átírás kész. Kattints a 'Beillesztés' gombra a cseréhez.")

    def _on_rewrite_error(self, msg):
        self.rewrite_btn.setEnabled(True)
        QMessageBox.critical(self, "Hiba", f"Átírás sikertelen:\n{msg}")
        self.status_bar.showMessage("Átírás sikertelen.")

    def _insert_rewrite(self):
        if not self._rewrite_result:
            return
        eredeti = self.selected_edit.toPlainText().strip()
        if not eredeti:
            return
        current = self.editor.toPlainText()
        updated = current.replace(eredeti, self._rewrite_result, 1)
        if updated != current:
            self.editor.setPlainText(updated)
            self.status_bar.showMessage("Szöveg beillesztve.")
        else:
            QMessageBox.information(
                self, "Nem találtam",
                "Az eredeti szövegrészlet már nem található a szerkesztőben."
            )

    # ── Auto-mentés / piszkozat ───────────────────────────────────────────

    def _autosave(self):
        if not self.editor.toPlainText().strip():
            return
        try:
            with open(self._draft_path, 'w', encoding='utf-8') as f:
                f.write("HTML:\n" + self.editor.toHtml())
        except Exception:
            pass

    def _restore_draft(self):
        if not os.path.exists(self._draft_path):
            return
        try:
            with open(self._draft_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                return
            ans = QMessageBox.question(
                self, "Piszkozat visszaállítása",
                "Van egy korábban mentett piszkozat. Visszaállítod?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ans == QMessageBox.StandardButton.Yes:
                if content.startswith("HTML:\n"):
                    self.editor.setHtml(content[6:])
                    # nincs "előző" szöveg, undo nem érhető el
                    self._before_beautify = ""
                    self._act_undo_beautify.setEnabled(False)
                else:
                    self.editor.setPlainText(content)
                    self._before_beautify = ""
        except Exception:
            pass

    def _on_data_popup(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Cégadatok szerkesztése")
        dlg.setMinimumSize(600, 500)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        editor = QPlainTextEdit()
        editor.setPlainText(self.data_edit.toPlainText())
        editor.setPlaceholderText("Cég neve: Példa Kft.\nProjekt költsége: 5 000 000 Ft\n...")
        editor.setStyleSheet(
            "border: 1px solid #cbd5e1; border-radius: 4px; "
            "padding: 6px; font-size: 13px; background: white;"
        )
        layout.addWidget(editor, stretch=1)

        btns = QDialogButtonBox()
        ok_btn = btns.addButton("Mentés", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = btns.addButton("Mégse", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.setStyleSheet("background:#2563eb; color:white; padding:6px 14px; border-radius:4px;")
        cancel_btn.setStyleSheet("padding:6px 14px; border-radius:4px;")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.data_edit.setPlainText(editor.toPlainText())

    def _on_reset_left(self):
        ans = QMessageBox.question(
            self, "Mezők törlése",
            "Biztosan törlöd a fájlokat, a feladat leírást és a cégadatokat?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        # Fájl gombok
        self._regi_path = None
        self._kiiras_path = None
        self._ceg_path = None
        self._tender_text = ""
        self._style_text = ""
        self.btn_regi.setText("  Régi pályázatok (stílustanulás)")
        self.btn_kiiras.setText("  Pályázati kiírás")
        self.btn_ceg.setText("  Cégadatlap (PDF/DOCX)")
        # Szövegmezők
        self.task_edit.clear()
        self.data_edit.clear()
        # Checklist elrejtése
        self.checklist_frame.setVisible(False)
        self._tender_info = {}
        self.status_bar.showMessage("Mezők törölve.")

    def _on_clear(self):
        if not self.editor.toPlainText().strip():
            return
        ans = QMessageBox.question(
            self, "Törlés megerősítése",
            "Biztosan törlöd a szerkesztőben lévő szöveget?\nA piszkozat is törlődik.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.editor.clear()
            self.score_label.setText("Pontszám: –")
            self.score_label.setStyleSheet("")
            self.checklist_frame.setVisible(False)
            try:
                if os.path.exists(self._draft_path):
                    os.remove(self._draft_path)
            except Exception:
                pass
            self.status_bar.showMessage("Szöveg törölve.")

    def closeEvent(self, event):
        self._autosave()
        self._save_session()
        event.accept()

    def _save_session(self):
        import json
        try:
            # Checkbox állapotok összegyűjtése
            checked_items = []
            for i in range(self.checklist_body_layout.count()):
                w = self.checklist_body_layout.itemAt(i).widget()
                if isinstance(w, QCheckBox) and w.isChecked():
                    checked_items.append(w.text())

            session = {
                "regi_path": self._regi_path,
                "kiiras_path": self._kiiras_path,
                "ceg_path": self._ceg_path,
                "task": self.task_edit.toPlainText(),
                "data": self.data_edit.toPlainText(),
                "rounds": self.rounds_spin.value(),
                "tender_info": self._tender_info,
                "checked_items": checked_items,
            }
            with open(self._session_path, 'w', encoding='utf-8') as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _restore_session(self):
        import json
        if not os.path.exists(self._session_path):
            return
        try:
            with open(self._session_path, 'r', encoding='utf-8') as f:
                session = json.load(f)

            # Fájl gombok felirata
            if session.get("regi_path") and os.path.exists(session["regi_path"]):
                self._regi_path = session["regi_path"]
                self.btn_regi.setText(f"  {os.path.basename(self._regi_path)}")
                self._load_text_async(self._regi_path, "style")

            if session.get("kiiras_path") and os.path.exists(session["kiiras_path"]):
                self._kiiras_path = session["kiiras_path"]
                self.btn_kiiras.setText(f"  {os.path.basename(self._kiiras_path)}")
                self._load_text_async(self._kiiras_path, "tender")

            if session.get("ceg_path") and os.path.exists(session["ceg_path"]):
                self._ceg_path = session["ceg_path"]
                self.btn_ceg.setText(f"  {os.path.basename(self._ceg_path)}")
                self._load_text_async(self._ceg_path, "data")

            # Szövegmezők
            if session.get("task"):
                self.task_edit.setPlainText(session["task"])
            if session.get("data"):
                self.data_edit.setPlainText(session["data"])
            if session.get("rounds"):
                self.rounds_spin.setValue(session["rounds"])

            # Checklist visszaállítása
            if session.get("tender_info"):
                self._tender_info = session["tender_info"]
                self._update_checklist()
                # Checkbox állapotok visszaállítása
                checked_items = set(session.get("checked_items", []))
                for i in range(self.checklist_body_layout.count()):
                    w = self.checklist_body_layout.itemAt(i).widget()
                    if isinstance(w, QCheckBox) and w.text() in checked_items:
                        w.setChecked(True)

        except Exception:
            pass

    # ── Word export ───────────────────────────────────────────────────────

    def _export_word(self):
        if not self.editor.toPlainText().strip():
            QMessageBox.warning(self, "Üres szöveg", "Nincs exportálható szöveg!")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Mentés Word formátumban", "palyazat.docx",
            "Word dokumentum (*.docx)"
        )
        if not path:
            return

        try:
            from text_beautifier import build_docx_from_editor_html
            build_docx_from_editor_html(self.editor.toHtml(), path)
            self.status_bar.showMessage(f"Exportálva: {os.path.basename(path)}")
            QMessageBox.information(self, "Sikeres export", f"Fájl mentve:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export hiba", str(e))

    # ── Stíluslap ─────────────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #f8fafc;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                color: #1e293b;
            }
            #leftPanel {
                background: #ffffff;
                border-right: 1px solid #e2e8f0;
            }
            #appTitle {
                font-size: 18px;
                font-weight: bold;
                color: #2563eb;
                margin-bottom: 4px;
            }
            #sectionLabel {
                font-weight: bold;
                color: #475569;
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            #fileBtn {
                background: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                text-align: left;
                padding-left: 8px;
                color: #334155;
            }
            #fileBtn:hover { background: #e2e8f0; }
            #genBtn {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            #genBtn:hover { background: #1d4ed8; }
            #genBtn:disabled { background: #93c5fd; }
            #resetBtn {
                background: #f1f5f9;
                color: #64748b;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                font-size: 12px;
            }
            #resetBtn:hover { background: #fee2e2; color: #dc2626; border-color: #fca5a5; }
            #cancelBtn {
                background: #ef4444;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            #cancelBtn:hover { background: #dc2626; }
            #cancelBtn:disabled { background: #fca5a5; }
            #rightPanel { background: #f8fafc; }
            #mainEditor {
                background: white;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 13px;
                padding: 8px;
            }
            #checkBtn {
                background: #fffbeb;
                color: #92400e;
                border: 1px solid #fde68a;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            #checkBtn:hover { background: #fef08a; }
            #checkBtn:disabled { color: #d97706; }
            #checklistFrame {
                background: #fffbeb;
                border: 1px solid #fde68a;
                border-radius: 6px;
            }
            #rewriteFrame {
                background: #f1f5f9;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }
            #rewriteBtn {
                background: #7c3aed;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            #rewriteBtn:hover { background: #6d28d9; }
            #rewriteBtn:disabled { background: #c4b5fd; }
            #navBtn {
                background: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                padding: 2px;
            }
            #navBtn:hover { background: #dbeafe; border-color: #93c5fd; }
            #navBtn:disabled { color: #cbd5e1; background: #f8fafc; }
            #rescoreBtn {
                background: #f1f5f9;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 4px 10px;
                font-size: 12px;
            }
            #rescoreBtn:hover { background: #dbeafe; border-color: #93c5fd; color: #2563eb; }
            #rescoreBtn:disabled { color: #94a3b8; }
            #clearBtn {
                background: #f1f5f9;
                color: #64748b;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: bold;
            }
            #clearBtn:hover { background: #fee2e2; color: #dc2626; border-color: #fca5a5; }
            #exportBtn {
                background: #059669;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: bold;
            }
            #exportBtn:hover { background: #047857; }
            QToolBar QToolButton {
                font-weight: bold;
                padding: 3px 7px;
                border: 1px solid #cbd5e1;
                border-radius: 3px;
                background: white;
            }
            QToolBar QToolButton:checked { background: #dbeafe; border-color: #93c5fd; }
            QToolBar QToolButton:hover { background: #f1f5f9; }
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                text-align: center;
                height: 16px;
            }
            QProgressBar::chunk { background: #2563eb; border-radius: 3px; }
            QSpinBox { border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px 20px 2px 6px; }
            QLineEdit, QPlainTextEdit, QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px;
                background: white;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
                border-color: #2563eb;
            }
        """)


# ── Belépési pont ──────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Pályázatíró")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
