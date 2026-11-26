from pathlib import Path
import sys

from PyQt5.QtCore import QDate, QTime, Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDateEdit, QDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from database import Database, DatabaseError, LOGIN_PATTERN
from shifts import format_duration, format_money, gross_minutes, make_shift, month_summary, parse_amount, parse_break

ROOT = Path(__file__).resolve().parent


def label(text="", style="", *, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(style)
    widget.setWordWrap(wrap)
    return widget


def button(text, style=""):
    widget = QPushButton(text)
    widget.setObjectName(style)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def panel(style, layout_type=QVBoxLayout, *, margins=24, spacing=12):
    frame = QFrame()
    frame.setObjectName(style)
    layout = layout_type(frame)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return frame, layout


def message(widget, text, *, success=False):
    widget.setProperty("success", success)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.setText(text)


def logo_row(size=46):
    layout = QHBoxLayout()
    layout.setSpacing(12)
    logo = QLabel()
    image = QPixmap(str(ROOT / "shiftpay.png"))
    logo.setPixmap(image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    logo.setFixedSize(size, size)
    layout.addWidget(logo)
    layout.addWidget(label("ShiftPay", "wordmark"))
    layout.addStretch()
    return layout


class AuthForm(QWidget):
    def __init__(self, registration):
        super().__init__()
        self.registration = registration
        self.setObjectName("authForm")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)
        layout.setAlignment(Qt.AlignVCenter)
        title = "Тіркелу" if registration else "Жүйеге кіру"
        subtitle = (
            "ShiftPay жүйесінде жеке тіркелгі ашыңыз."
            if registration else "Ауысымдар журналына кіру үшін тіркелгіңізді пайдаланыңыз."
        )
        layout.addWidget(label(title, "heading"))
        layout.addWidget(label(subtitle, "subtitle", wrap=True))
        layout.addSpacing(12)

        layout.addWidget(label("Логин", "fieldLabel"))
        self.login = QLineEdit()
        self.login.setPlaceholderText("Мысалы, janat")
        self.login.setAccessibleName("Логин")
        self.login.setMaxLength(32)
        layout.addWidget(self.login)

        layout.addWidget(label("Құпиясөз", "fieldLabel"))
        self.password = QLineEdit()
        self.password.setPlaceholderText("Кемінде 8 таңба" if registration else "Құпиясөзді енгізіңіз")
        self.password.setAccessibleName("Құпиясөз")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMaxLength(128)
        layout.addWidget(self.password)

        if registration:
            layout.addWidget(label("Құпиясөзді қайталаңыз", "fieldLabel"))
            self.confirm = QLineEdit()
            self.confirm.setPlaceholderText("Құпиясөзді қайта енгізіңіз")
            self.confirm.setAccessibleName("Құпиясөзді қайталаңыз")
            self.confirm.setEchoMode(QLineEdit.Password)
            self.confirm.setMaxLength(128)
            layout.addWidget(self.confirm)

        self.feedback = label("", "message", wrap=True)
        self.feedback.setMinimumHeight(34)
        layout.addWidget(self.feedback)
        self.submit = button("Тіркелу" if registration else "Кіру", "primary")
        self.switch = button("Кіру бетіне қайту" if registration else "Тіркелу", "secondary")
        layout.addWidget(self.submit)
        layout.addWidget(self.switch)
        self.login.returnPressed.connect(self.password.setFocus)
        if registration:
            self.password.returnPressed.connect(self.confirm.setFocus)
            self.confirm.returnPressed.connect(self.submit.click)
        else:
            self.password.returnPressed.connect(self.submit.click)

    def credentials(self):
        login = self.login.text().strip().lower()
        password = self.password.text()
        if not login or not password.strip() or (self.registration and not self.confirm.text().strip()):
            raise ValueError("Барлық өрісті толтырыңыз.")
        if self.registration:
            if not LOGIN_PATTERN.fullmatch(login):
                raise ValueError("Логин 3–32 таңба: a–z, 0–9, нүкте, сызықша немесе астын сызу.")
            if len(password) < 8:
                raise ValueError("Құпиясөз кемінде 8 таңбадан тұруы керек.")
            if password != self.confirm.text():
                raise ValueError("Құпиясөздер сәйкес келмейді.")
        return login, password

    def clear_passwords(self):
        self.password.clear()
        if self.registration:
            self.confirm.clear()


class ShiftDialog(QDialog):
    def __init__(self, owner, user_id, selected_date):
        super().__init__(owner)
        self.user_id = user_id
        self.shift = None
        self.setWindowTitle("ShiftPay · Ауысым қосу")
        self.setMinimumWidth(510)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)
        layout.addWidget(label("Ауысым қосу", "dialogHeading"))
        layout.addWidget(label("Уақыт пен төлем шарттарын енгізіңіз.", "subtitle"))
        fields = QGridLayout()
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(8)
        layout.addLayout(fields)

        self.date = QDateEdit(selected_date)
        self.date.setDateRange(QDate(1900, 1, 1), QDate(2099, 12, 31))
        self.date.setDisplayFormat("dd.MM.yyyy")
        self.date.setCalendarPopup(True)
        self.start = QTimeEdit(QTime(16, 0))
        self.end = QTimeEdit(QTime(1, 0))
        self.start.setDisplayFormat("HH:mm")
        self.end.setDisplayFormat("HH:mm")
        self.rest = QSpinBox()
        self.rest.setRange(0, 1438)
        self.rest.setValue(30)
        self.rest.setSuffix(" мин")
        self.pay_type = QComboBox()
        self.pay_type.addItem("Сағаттық", "hourly")
        self.pay_type.addItem("Бекітілген", "fixed")
        self.amount = QLineEdit("1100")
        self.amount.setMaxLength(12)
        for index, (name, widget) in enumerate((
            ("Ауысым күні", self.date), ("Үзіліс", self.rest),
            ("Басталуы", self.start), ("Аяқталуы", self.end),
            ("Төлем түрі", self.pay_type), ("Мөлшерлеме / сома (₸)", self.amount),
        )):
            row, col = divmod(index, 2)
            widget.setAccessibleName(name)
            fields.addWidget(label(name, "fieldLabel"), row * 2, col)
            fields.addWidget(widget, row * 2 + 1, col)

        preview, preview_layout = panel("preview", margins=16, spacing=5)
        self.preview_amount = label("", "metric")
        self.preview_details = label("", "caption", wrap=True)
        preview_layout.addWidget(self.preview_amount)
        preview_layout.addWidget(self.preview_details)
        layout.addWidget(preview)

        actions = QHBoxLayout()
        cancel = button("Бас тарту")
        self.save = button("Ауысымды сақтау", "primary")
        self.save.setDefault(True)
        actions.addWidget(cancel)
        actions.addWidget(self.save, 1)
        layout.addLayout(actions)
        cancel.clicked.connect(self.reject)
        self.save.clicked.connect(self.finish)
        self.date.dateChanged.connect(self.update_preview)
        self.start.timeChanged.connect(self.update_preview)
        self.end.timeChanged.connect(self.update_preview)
        self.rest.valueChanged.connect(self.update_preview)
        self.pay_type.currentIndexChanged.connect(self.update_preview)
        self.amount.textChanged.connect(self.update_preview)
        self.update_preview()

    def calculate(self):
        day = self.date.date().toPyDate()
        start = self.start.time().toString("HH:mm")
        end = self.end.time().toString("HH:mm")
        rest = parse_break(str(self.rest.value()), gross_minutes(day, start, end))
        return make_shift(self.user_id, day, start, end, rest, self.pay_type.currentData(),
                          parse_amount(self.amount.text().strip()))

    def update_preview(self):
        try:
            shift = self.calculate()
        except ValueError as error:
            self.preview_amount.setText("Есептеу мүмкін емес")
            self.preview_details.setText(str(error))
            self.save.setEnabled(False)
            return
        self.preview_amount.setText(format_money(shift.total))
        next_day = " · Ауысым келесі күні аяқталады" if shift.end < shift.start else ""
        self.preview_details.setText("Таза жұмыс уақыты " + format_duration(shift.work_minutes) + next_day)
        self.save.setEnabled(True)

    def finish(self):
        try:
            self.shift = self.calculate()
        except ValueError:
            self.update_preview()
            return
        self.accept()


class Dashboard(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.rows = []
        self.user_id = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        side, sidebar = panel("sidebar", margins=18)
        side.setFixedWidth(205)
        sidebar.addLayout(logo_row(39))
        sidebar.addSpacing(25)
        sidebar.addWidget(label("Ауысымдар журналы", "heroCaption"))
        sidebar.addStretch()
        self.account = label("", "heroCopy", wrap=True)
        sidebar.addWidget(self.account)
        logout = button("Шығу", "logout")
        logout.clicked.connect(window.logout)
        sidebar.addWidget(logout)
        layout.addWidget(side)

        body = QVBoxLayout()
        body.setSpacing(15)
        layout.addLayout(body, 1)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(label("Ауысымдар", "heading"))
        heading.addWidget(label("Жұмыс уақыты мен төлемдерді қадағалаңыз.", "subtitle", wrap=True))
        header.addLayout(heading, 1)
        add = button("+ Ауысым қосу", "primary")
        add.clicked.connect(self.add_shift)
        header.addWidget(add)
        body.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.metrics = []
        for title, value in zip(
            ("Жұмыс уақыты", "Есептелді", "Төленді", "Төленбеді"),
            ("0 сағ 00 мин", "0,00 ₸", "0,00 ₸", "0,00 ₸"),
        ):
            card, contents = panel("surface", margins=13, spacing=5)
            contents.addWidget(label(title, "caption"))
            metric = label(value, "metric")
            self.metrics.append(metric)
            contents.addWidget(metric)
            stats.addWidget(card, 1)
        body.addLayout(stats)

        journal, journal_layout = panel("surface", margins=17)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("Ауысымдар журналы", "sectionTitle"), 1)
        toolbar.addWidget(label("Ай", "fieldLabel"))
        self.month = QDateEdit(QDate.currentDate())
        self.month.setDisplayFormat("MM.yyyy")
        self.month.setDateRange(QDate(1900, 1, 1), QDate(2099, 12, 31))
        self.month.setAccessibleName("Есеп айы")
        toolbar.addWidget(self.month)
        journal_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Күні", "Уақыты", "Ұзақтығы", "Сомасы", "Мәртебесі"))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        journal_layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.status = label("", "caption", wrap=True)
        footer.addWidget(self.status, 1)
        self.paid_button = button("Төленді деп белгілеу")
        self.paid_button.setEnabled(False)
        footer.addWidget(self.paid_button)
        journal_layout.addLayout(footer)
        body.addWidget(journal, 1)
        self.month.dateChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self.update_paid_button)
        self.paid_button.clicked.connect(self.toggle_paid)

    def open_account(self, user_id, login):
        self.user_id = user_id
        self.account.setText(login)
        self.month.blockSignals(True)
        self.month.setDate(QDate.currentDate())
        self.month.blockSignals(False)
        self.refresh()

    def refresh(self):
        if self.user_id is None:
            return
        month = self.month.date().toPyDate().replace(day=1)
        result = self.window.database_call(lambda db: db.shifts_for_month(self.user_id, month))
        self.rows = result if result is not None else []
        self.table.clearSelection()
        self.table.setRowCount(len(self.rows))
        minutes, total, paid, unpaid = month_summary(self.rows)
        for metric, value in zip(self.metrics, (
            format_duration(minutes), format_money(total), format_money(paid), format_money(unpaid),
        )):
            metric.setText(value)
        for index, row in enumerate(self.rows):
            is_paid = row["paid"] == "yes"
            overnight = " +1" if row["end"] < row["start"] else ""
            values = (
                row["shift_date"], f'{row["start"]}–{row["end"]}{overnight}',
                format_duration(row["work_minutes"]), format_money(row["total"]),
                "Төленді" if is_paid else "Төленбеді",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setForeground(QColor("#27613A" if is_paid else "#854F17"))
                self.table.setItem(index, column, item)
        if result is None:
            self.status.setText("Журналды жүктеу мүмкін болмады.")
        else:
            self.status.setText(
                f"{len(self.rows)} ауысым" if self.rows else "Осы айда ауысымдар тіркелмеген."
            )
        self.update_paid_button()

    def add_shift(self):
        today = QDate.currentDate()
        active = self.month.date()
        initial = today if (today.year(), today.month()) == (active.year(), active.month()) else active
        dialog = ShiftDialog(self, self.user_id, initial)
        if dialog.exec_() != QDialog.Accepted:
            return
        shift = dialog.shift
        if self.window.database_call(lambda db: db.save_shift(shift)):
            day = shift.shift_date
            self.month.blockSignals(True)
            self.month.setDate(QDate(day.year, day.month, day.day))
            self.month.blockSignals(False)
            self.refresh()

    def selected_shift(self):
        indexes = self.table.selectionModel().selectedRows()
        return self.rows[indexes[0].row()] if indexes else None

    def update_paid_button(self):
        row = self.selected_shift()
        self.paid_button.setEnabled(row is not None)
        undo = row is not None and row["paid"] == "yes"
        self.paid_button.setText("Төленбеді деп белгілеу" if undo else "Төленді деп белгілеу")

    def toggle_paid(self):
        row = self.selected_shift()
        if row is None:
            return
        self.window.database_call(lambda db: db.mark_paid(
            self.user_id, row["shift_id"], row["paid"] != "yes"
        ))
        self.refresh()


class ShiftPayWindow(QMainWindow):
    def __init__(self, database=None):
        super().__init__()
        self.database = database
        self.setWindowTitle("ShiftPay")
        self.setWindowIcon(QIcon(str(ROOT / "shiftpay.png")))
        self.setMinimumSize(930, 650)
        self.resize(1080, 700)

        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        auth = QWidget()
        layout = QHBoxLayout(auth)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(19)
        hero, hero_layout = panel("hero", margins=34, spacing=16)
        hero_layout.addLayout(logo_row())
        hero_layout.addStretch(2)
        hero_layout.addWidget(label("Жұмыс уақыты\nмен ауысым ақысы", "heroTitle", wrap=True))
        hero_layout.addWidget(label(
            "Ауысымдарды тіркеңіз, еңбекақыны есептеңіз және төлем мәртебесін бақылаңыз.",
            "heroCopy", wrap=True,
        ))
        hero_layout.addStretch(1)
        example, details = panel("heroExample", margins=17, spacing=5)
        details.addWidget(label("Түнгі ауысым мысалы", "heroCaption"))
        details.addWidget(label("9 350 ₸", "heroAmount"))
        details.addWidget(label("16:00–01:00  ·  8 сағ 30 мин", "heroCaption"))
        hero_layout.addWidget(example)
        layout.addWidget(hero, 10)

        card, card_layout = panel("formCard", margins=39)
        card_layout.addStretch()
        self.forms = QStackedWidget()
        self.forms.setObjectName("authForms")
        self.login_form = AuthForm(False)
        self.registration_form = AuthForm(True)
        self.forms.addWidget(self.login_form)
        self.forms.addWidget(self.registration_form)
        card_layout.addWidget(self.forms)
        card_layout.addStretch()
        layout.addWidget(card, 11)
        self.pages.addWidget(auth)
        self.dashboard = Dashboard(self)
        self.pages.addWidget(self.dashboard)

        self.login_form.switch.clicked.connect(self.show_registration)
        self.registration_form.switch.clicked.connect(self.show_login)
        self.login_form.submit.clicked.connect(self.login)
        self.registration_form.submit.clicked.connect(self.register)
        self.login_form.login.setFocus()

    def show_registration(self):
        self.login_form.clear_passwords()
        self.registration_form.login.setText(self.login_form.login.text())
        self.registration_form.clear_passwords()
        message(self.registration_form.feedback, "")
        self.forms.setCurrentWidget(self.registration_form)
        self.registration_form.login.setFocus()

    def show_login(self):
        self.registration_form.clear_passwords()
        message(self.login_form.feedback, "")
        self.forms.setCurrentWidget(self.login_form)
        self.login_form.login.setFocus()

    def database_call(self, action):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.database is None:
                self.database = Database()
            return action(self.database)
        except (DatabaseError, OSError) as error:
            details = str(error)
        finally:
            QApplication.restoreOverrideCursor()
        dialog = QMessageBox(QMessageBox.Warning, "Дерекқор қатесі",
                             "PostgreSQL операциясы орындалмады.", QMessageBox.Ok, self)
        dialog.setDetailedText(details)
        dialog.exec_()
        return None

    def register(self):
        form = self.registration_form
        try:
            login, password = form.credentials()
        except ValueError as error:
            message(form.feedback, str(error))
            return
        created = self.database_call(lambda db: db.register(login, password))
        if created is False:
            message(form.feedback, "Бұл логин бос емес. Басқа логин таңдаңыз.")
        if created:
            self.show_login()
            self.login_form.login.setText(login)
            message(self.login_form.feedback, "Тіркелу сәтті аяқталды. Енді жүйеге кіріңіз.", success=True)
            self.login_form.password.setFocus()

    def login(self):
        form = self.login_form
        try:
            login, password = form.credentials()
        except ValueError as error:
            message(form.feedback, str(error))
            return
        result = self.database_call(lambda db: db.authenticate(login, password))
        if result is None:
            return
        if result is False:
            form.clear_passwords()
            message(form.feedback, "Логин немесе құпиясөз қате.")
            form.password.setFocus()
            return
        form.clear_passwords()
        message(form.feedback, "")
        self.pages.setCurrentWidget(self.dashboard)
        self.dashboard.open_account(result, login)

    def logout(self):
        self.dashboard.user_id = None
        self.dashboard.rows = []
        self.dashboard.table.setRowCount(0)
        self.pages.setCurrentIndex(0)
        self.show_login()
        self.login_form.login.clear()
        self.login_form.clear_passwords()


def make_app():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet((ROOT / "style.qss").read_text(encoding="utf-8"))
    return app


if __name__ == "__main__":
    app = make_app()
    window = ShiftPayWindow()
    window.show()
    sys.exit(app.exec_())
