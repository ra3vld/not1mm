"""New Contest Dialog"""

from PyQt6 import QtWidgets

from not1mm.lib.i18n import load_ui
from not1mm.udc import registry


class NewContest(QtWidgets.QDialog):
    """New Contest"""

    def __init__(self, app_data_path):
        super().__init__(None)
        load_ui(self, app_data_path / "new_contest.ui")
        self.contest.clear()
        for identifier, label in registry.entries():
            self.contest.addItem(label, identifier)
        self.buttonBox.clicked.connect(self.store)
        self.contest.currentTextChanged.connect(self.add_exchange_hint)

    def store(self):
        """dialog magic"""

    def add_exchange_hint(self):
        """add hint"""
        self.soapbox.setPlaceholderText("")
        self.exchange.setPlaceholderText("")
        contest_name = self.contest.currentData()
        try:
            temp = registry.load(contest_name)
            if hasattr(temp, "EXCHANGE_HINT"):
                self.exchange.setPlaceholderText(temp.EXCHANGE_HINT)
            else:
                self.exchange.setPlaceholderText("")
            if hasattr(temp, "SOAPBOX_HINT"):
                self.soapbox.setPlaceholderText(temp.SOAPBOX_HINT)
            else:
                self.soapbox.setPlaceholderText("")
        except ModuleNotFoundError:
            ...
