# assembly.py
import os
import sys
import re
import datetime
import configparser

try:
    import win32print
except ImportError:  # pragma: no cover - only needed for desktop printer support
    win32print = None

try:
    from PyQt5 import QtWidgets, uic
    from PyQt5.QtWidgets import QApplication, QHeaderView, QMessageBox, QTableWidget, QTableWidgetItem
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QColor, QPixmap
except ImportError:  # pragma: no cover - web/backend import does not require GUI
    QtWidgets = None
    uic = None
    QApplication = None
    QHeaderView = None
    QMessageBox = None
    QTableWidget = None
    QTableWidgetItem = None
    Qt = type("QtStub", (), {"KeepAspectRatio": 0, "SmoothTransformation": 0})()
    QColor = None
    QPixmap = None

import pymysql
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

if getattr(sys, "frozen", False):
    BASE_DIR   = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

load_dotenv(os.path.join(BASE_DIR, ".env"))

ui_candidates = [
    os.path.join(BUNDLE_DIR, "pairing.ui"),
    os.path.join(BUNDLE_DIR, "assembly.ui"),
]
UI_FILE = next((p for p in ui_candidates if os.path.exists(p)), ui_candidates[0])
CONFIG_FILE = os.path.join(BASE_DIR,   "printer_config.txt")
ZPL_FILE    = os.path.join(BASE_DIR,   "label.txt")
QR_ZPL_FILE = os.path.join(BASE_DIR,   "qr_label.txt")

# ─────────────────────────────────────────────
# CONFIG / SETTINGS
# ─────────────────────────────────────────────

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.ini")


def load_settings(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    if os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    return cfg


SETTINGS = load_settings(SETTINGS_FILE)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

DB_HOST = os.getenv("DB_HOST", SETTINGS.get("database", "db_host", fallback="192.168.1.38"))
DB_PORT = int(os.getenv("DB_PORT", SETTINGS.get("database", "db_port", fallback="3306")))
DB_USER = os.getenv("DB_USER", SETTINGS.get("database", "db_user", fallback="labeling"))
DB_PASS = os.getenv("DB_PASSWORD", SETTINGS.get("database", "db_password", fallback="labeling"))

DB_NAME = SETTINGS.get("database", "db_name", fallback="cre_tech")
TABLE = SETTINGS.get("database", "assembly_table", fallback=f"{DB_NAME}.gensys_assembly")
MAIN_TABLE = SETTINGS.get("database", "main_table", fallback=f"{DB_NAME}.gensys_main")
MAX_FAIL_TESTS = 3

def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )

def check_operator(emp_num: str) -> bool:
    query = SETTINGS.get(
        "queries",
        "operator_check_query",
        fallback="SELECT 1 FROM operators.`main` WHERE operator_en = %s LIMIT 1",
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (emp_num,))
            return cur.fetchone() is not None

def insert_assembly(record: dict) -> None:
    query = SETTINGS.get(
        "queries",
        "insert_assembly_query",
        fallback="""
            INSERT INTO {table}
                (serial_num, po_num, operator_en, shift,
                 date_time, customer_sn, test_rep, remarks, status)
            VALUES
                (%(serial_num)s, %(po_num)s, %(operator_en)s, %(shift)s,
                 %(date_time)s, %(customer_sn)s, %(test_rep)s,
                 %(remarks)s, %(status)s)
        """,
    )
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(query.format(table=TABLE), record)
            conn.commit()
        except pymysql.IntegrityError as e:
            raise RuntimeError(f"Duplicate or constraint error: {e}") from e
  
def insert_ems_main(record: dict) -> None:
    query = SETTINGS.get(
        "queries",
        "insert_main_query",
        fallback="""
            INSERT INTO {main_table}
                (serial_num, po_num, soldering,
                 cleaning, vi, progtest, insulation, assembly, lasermarking, fvi, packing, packaging)
            VALUES
                (%(serial_num)s, %(po_num)s, %(soldering)s,
                 %(cleaning)s, %(vi)s, %(progtest)s, %(insulation)s, %(assembly)s, %(lasermarking)s, %(fvi)s, %(packing)s, %(packaging)s)
            ON DUPLICATE KEY UPDATE
                po_num = VALUES(po_num),
                soldering = VALUES(soldering),
                cleaning = VALUES(cleaning),
                vi = VALUES(vi),
                progtest = VALUES(progtest),
                insulation = VALUES(insulation),
                assembly = VALUES(assembly),
                lasermarking = VALUES(lasermarking),
                fvi = VALUES(fvi),
                packing = VALUES(packing),
                packaging = VALUES(packaging)
        """,
    )
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(query.format(main_table=MAIN_TABLE), record)
            conn.commit()
        except pymysql.IntegrityError as e:
            raise RuntimeError(f"Duplicate or constraint error: {e}") from e


def normalize_serial_base(serial_num: str) -> str:
    serial = (serial_num or "").strip()
    if "_" not in serial:
        return serial
    base, _, suffix = serial.rpartition("_")
    if suffix.isdigit():
        return base
    return serial


def build_fail_serial_num(serial_num: str, fail_count: int) -> str:
    base = normalize_serial_base(serial_num)
    return f"{base}_{fail_count + 1}"


def is_fail_limit_reached(fail_count: int) -> bool:
    return fail_count >= MAX_FAIL_TESTS


def get_fail_count_for_serial(serial_num: str) -> int:
    base = normalize_serial_base(serial_num)
    query = SETTINGS.get(
        "queries",
        "fail_count_query",
        fallback="""
            SELECT COUNT(*) AS cnt
            FROM {table}
            WHERE (serial_num = %s OR serial_num LIKE %s)
              AND status = 0
        """,
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query.format(table=TABLE), (serial_num, f"{base}_%"))
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0
# ─────────────────────────────────────────────
# SERIAL / BATCH CODE GENERATION
# ─────────────────────────────────────────────

def get_next_unit_count() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM {TABLE} WHERE DATE(date_time) = CURDATE()"
            )
            row = cur.fetchone()
            return (row["cnt"] if row else 0) + 1


def _date_parts() -> tuple[str, str]:
    """Return (2-digit year, zero-padded Julian day) for today."""
    now = datetime.datetime.now()
    return str(now.year)[-2:], str(now.timetuple().tm_yday).zfill(3)


def build_serial_num(unit_count: int) -> str:
    year, jdate = _date_parts()
    return f"KPME{year}{jdate}{unit_count:04d}"


def build_batch_code(unit_count: int) -> str:
    year, jdate = _date_parts()
    group = str(((unit_count - 1) // 100) + 1).zfill(2)
    return f"{year}{jdate}{group}"

def parse_panel_sn(serial_num: str) -> str:
    """Extract panel SN (KPME + year + julian day) from a full serial number.
    e.g. 'KPME261590001' → 'KPME26159'
    """
    return serial_num[:9]  # 'KPME' (4) + year (2) + julian day (3)


def parse_series_num(serial_num: str) -> str:
    """Extract the 4-digit unit sequence from a full serial number.
    e.g. 'KPME261590001' → '0001'
    """
    return serial_num[9:]  # everything after the 9-char prefix
# ─────────────────────────────────────────────
# PRINTER
# ─────────────────────────────────────────────

def load_config(path: str) -> dict:
    config: dict[str, str] = {}
    if not os.path.exists(path):
        return config
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip().upper()] = value.strip()
    return config


def load_zpl(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"ZPL file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def inject_zpl_values(zpl: str, serial_num: str, batch_code: str) -> str:
    replacements = iter([serial_num, batch_code])

    def _replacer(m: re.Match) -> str:
        try:
            return f"{m.group(1)}{next(replacements)}{m.group(2)}"
        except StopIteration:
            return m.group(0)

    zpl = re.sub(r"(\^A0N,77,71\^FD)[^\^]+(\^FS)", _replacer, zpl)
    zpl = re.sub(
        r"(\^FD\\&\(01\)PEMS05\(10\))[^\^]+(\(21\))[^\^]+(\^FS)",
        lambda m: f"{m.group(1)}{batch_code}{m.group(2)}{serial_num}{m.group(3)}",
        zpl,
    )
    today = datetime.datetime.now().strftime("%Y %m %d")
    return zpl.replace("{DATE}", today)


def build_qr_zpl(serial_num: str) -> str:
    """Load qr_label.txt and inject the serial number."""
    zpl = load_zpl(QR_ZPL_FILE)
    return zpl.replace("{SERIAL}", serial_num)


def printer_exists(name: str) -> bool:
    if win32print is None:
        return False
    printers = win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    )
    return name in {p[2] for p in printers}


def send_to_printer(zpl: str, printer_name: str) -> None:
    if win32print is None:
        raise RuntimeError("Windows print support is not available in this environment.")
    hp = win32print.OpenPrinter(printer_name)
    try:
        win32print.StartDocPrinter(hp, 1, ("ZPL Label", None, "RAW"))
        win32print.StartPagePrinter(hp)
        win32print.WritePrinter(hp, zpl.encode("utf-8"))
        win32print.EndPagePrinter(hp)
        win32print.EndDocPrinter(hp)
    finally:
        win32print.ClosePrinter(hp)

# ─────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────

if QtWidgets is not None:
    class MainWindow(QtWidgets.QMainWindow):

        def __init__(self):
            super().__init__()
            uic.loadUi(UI_FILE, self)
            self._fix_bundled_pixmaps()

            self.logged_in      = False
            self.operator       = ""
            self.shift          = ""
            self.mainboard_rec  = None
            self.suiteboard_rec = None
            self.operator_en.setFocus()

            self._setup()

        # ── INIT HELPERS ─────────────────────────────

        def _fix_bundled_pixmaps(self) -> None:
            """Re-apply pixmaps whose paths may differ inside a PyInstaller bundle."""
            import xml.etree.ElementTree as ET

            try:
                tree = ET.parse(UI_FILE)
            except Exception:
                return

            pixmap_map: dict[str, str] = {}
            for widget in tree.iter("widget"):
                name = widget.get("name", "")
                for prop in widget.iter("property"):
                    if prop.get("name") == "pixmap":
                        el = prop.find("pixmap")
                        if el is not None and el.text:
                            pixmap_map[name] = os.path.basename(el.text.strip())

            for widget_name, fname in pixmap_map.items():
                label = self.findChild(QtWidgets.QLabel, widget_name)
                if label is None:
                    continue
                full_path = os.path.join(BUNDLE_DIR, fname)
                if not os.path.exists(full_path):
                    continue
                px = QPixmap(full_path)
                if px.isNull():
                    continue
                label.setPixmap(
                    px.scaled(label.width(), label.height(),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )

        def _setup(self) -> None:
            self.setWindowTitle("Pepper EMS – assembly Station")

            self._load_logo(self.label_4, "Pepper-Logo-Horizontal-Transparent-BG@3x.png")
            self._load_logo(self.label_7, "image.png")

            if self.shift_comboBox.count() == 0:
                self.shift_comboBox.addItems(["A", "B", "C"])

            self.scan_sn.setEnabled(False)
            self.scan_customersn.setEnabled(False)
            self.passButton.setEnabled(False)
            self.failButton.setEnabled(False)
            self.reason_fail.setEnabled(False)
            self.pairing_label_loading_identifyer.setText("")

            # self._setup_table()
            self._connect_signals()

            cfg = load_config(CONFIG_FILE)
            self.printer_name = cfg.get("PRINTER", "")

            # self._refresh_table()

        def _load_logo(self, label: QtWidgets.QLabel, filename: str) -> None:
            path = os.path.join(BUNDLE_DIR, filename)
            if not os.path.exists(path):
                return
            px = QPixmap(path)
            if not px.isNull():
                label.setPixmap(px)

        def _connect_signals(self) -> None:
            self.operator_en.textChanged.connect(self._force_upper_operator)
            self.operator_en.returnPressed.connect(self._do_login)
            self.login_button.clicked.connect(self._do_login)
            self.scan_sn.returnPressed.connect(self._do_pair)
            self.scan_customersn.returnPressed.connect(self._do_pair)
            self.passButton.clicked.connect(self._do_pair)
            self.failButton.clicked.connect(self._do_fail)

        # ── LOGIN ────────────────────────────────────

        def _force_upper_operator(self, text: str) -> None:
            upper = text.upper()
            if text == upper:
                return
            pos = self.operator_en.cursorPosition()
            self.operator_en.blockSignals(True)
            self.operator_en.setText(upper)
            self.operator_en.setCursorPosition(pos)
            self.operator_en.blockSignals(False)

        def _do_login(self) -> None:
            emp = self.operator_en.text().strip()
            if not emp:
                self._set_status("Enter employee number.", warn=True)
                return

            self._set_status("Checking operator…")
            QApplication.processEvents()

            try:
                found = check_operator(emp)
            except Exception as e:
                self._set_status(f"DB error: {e}", warn=True)
                return

            if not found:
                self._set_status(f"✗ Employee '{emp}' not in database.", warn=True)
                return

            self.logged_in = True
            self.operator  = emp
            self.shift     = self.shift_comboBox.currentText()

            self.operator_en.setEnabled(False)
            self.shift_comboBox.setEnabled(False)
            self.login_button.setText("✓ Logged in")
            self.login_button.setEnabled(False)
            self.passButton.setEnabled(True)
            self.failButton.setEnabled(True)

            self.scan_sn.setEnabled(True)
            self.scan_customersn.setEnabled(True)
            self.scan_sn.setFocus()

            self._set_status(f"✓ Logged in: {emp}  |  Shift {self.shift}")

        # ── PAIR & PRINT ─────────────────────────────

        def _do_pair(self) -> None:
            if not self.logged_in:
                self._set_status("Login required before saving.", warn=True)
                return

            serial_num = self.scan_sn.text().strip()
            customer_sn = self.scan_customersn.text().strip()
            po_num = self.input_ponum.text().strip()

            if not serial_num:
                self._set_status("Scan the serial number first.", warn=True)
                return
            if not po_num:
                self._set_status("Enter the PO number before saving.", warn=True)
                self.input_ponum.setFocus()
                return

            self._set_status("Saving scan…")
            self.passButton.setEnabled(False)
            self.failButton.setEnabled(False)
            QApplication.processEvents()

            try:
                record = {
                    "serial_num": serial_num,
                    "po_num": po_num,
                    "operator_en": self.operator,
                    "shift": self.shift,
                    "date_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "customer_sn": customer_sn,
                    "test_rep": 1,
                    "remarks": " ",
                    "status": 1,
                }
                insert_assembly(record)

                ems_main_record = {
                    "serial_num": serial_num,
                    "po_num": po_num,
                    "soldering": 0,
                    "cleaning": 0,
                    "vi": 0,
                    "progtest": 0,
                    "insulation": 0,
                    "assembly": 1,
                    "lasermarking": 0,
                    "fvi": 0,
                    "packing": 0,
                    "packaging": 0,
                }
                insert_ems_main(ems_main_record)

            except Exception as e:
                QMessageBox.critical(
                    self, "Database Error",
                    f"Failed to save scan record.\n\n"
                    f"Serial : {serial_num}\n"
                    f"Customer: {customer_sn or '(empty)'}\n\n"
                    f"Error  : {e}",
                )
                self._set_status(f"✗ DB error: {e}", warn=True)
                self.passButton.setEnabled(True)
                self.failButton.setEnabled(True)
                return

            self._set_status(f"✓ Saved  |  Serial: {serial_num}")
            self._reset_scan()

        def _do_fail(self) -> None:
            if not self.logged_in:
                self._set_status("Login required before saving fail.", warn=True)
                return

            serial_num = self.scan_sn.text().strip()
            po_num = self.input_ponum.text().strip()
            if not serial_num:
                self._set_status("Scan the serial number first.", warn=True)
                return
            if not po_num:
                self._set_status("Enter the PO number before saving the fail.", warn=True)
                self.input_ponum.setFocus()
                return

            self.reason_fail.setEnabled(True)
            self.reason_fail.setFocus()
            reason = self.reason_fail.text().strip()
            if not reason:
                self._set_status("Enter a failure reason before saving.", warn=True)
                return

            fail_count = get_fail_count_for_serial(serial_num)
            if is_fail_limit_reached(fail_count):
                QMessageBox.critical(
                    self,
                    "FA Team Endorsement Required",
                    f"Serial {serial_num} has already reached {MAX_FAIL_TESTS} failed tests.\n"
                    "Please endorse this unit to the FA team now.",
                )
                self._set_status(f"✗ Max fail reached for {serial_num}. Please endorse to FA team.", warn=True)
                self.scan_sn.clear()
                self.scan_customersn.clear()
                self.input_ponum.clear()
                self.reason_fail.clear()
                return

            next_fail_num = fail_count + 1
            fail_serial = build_fail_serial_num(serial_num, fail_count)
            self._set_status("Saving fail record…")
            self.passButton.setEnabled(False)
            self.failButton.setEnabled(False)
            QApplication.processEvents()

            try:
                record = {
                    "serial_num": fail_serial,
                    "po_num": po_num,
                    "operator_en": self.operator,
                    "shift": self.shift,
                    "date_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "customer_sn": self.scan_customersn.text().strip(),
                    "test_rep": next_fail_num,
                    "remarks": reason,
                    "status": 0,
                }
                insert_assembly(record)

                ems_main_record = {
                    "serial_num": serial_num,
                    "po_num": po_num,
                    "soldering": 0,
                    "cleaning": 0,
                    "vi": 0,
                    "progtest": 0,
                    "insulation": 0,
                    "assembly": 1,
                    "lasermarking": 0,
                    "fvi": 0,
                    "packing": 0,
                    "packaging": 0,
                }
                insert_ems_main(ems_main_record)

            except Exception as e:
                QMessageBox.critical(
                    self, "Database Error",
                    f"Failed to save fail record.\n\n"
                    f"Serial : {serial_num}\n"
                    f"Reason : {reason}\n\n"
                    f"Error  : {e}",
                )
                self._set_status(f"✗ DB error: {e}", warn=True)
                self.passButton.setEnabled(True)
                self.failButton.setEnabled(True)
                return

            self._set_status(f"✓ Fail saved  |  Serial: {fail_serial}  |  Test fail: {next_fail_num}/{MAX_FAIL_TESTS}")
            self.reason_fail.clear()
            self.reason_fail.setEnabled(False)
            self._reset_scan()

        # ── HELPERS ──────────────────────────────────

        def _set_status(self, msg: str, warn: bool = False) -> None:
            self.pairing_label_loading_identifyer.setText(msg)

        def _reset_scan(self) -> None:
            self.scan_sn.clear()
            self.scan_customersn.clear()
            self.input_ponum.clear()
            self.reason_fail.clear()
            self.reason_fail.setEnabled(False)
            # self.scan_customersn.setEnabled(False)
            self.passButton.setEnabled(True)
            self.failButton.setEnabled(True)
            self.scan_sn.setFocus()

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if QtWidgets is not None:
    def main() -> None:
        if QApplication is None:
            raise RuntimeError("PyQt5 is required to launch the desktop pairing station UI.")
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        win = MainWindow()
        win.show()
        sys.exit(app.exec_())


if __name__ == "__main__":
    if QtWidgets is None:
        raise RuntimeError("The desktop UI is unavailable in this environment. Use the Flask web backend instead.")
    main()