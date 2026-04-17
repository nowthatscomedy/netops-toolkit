from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.app_state import AppState
from app.utils.file_utils import open_in_explorer
from app.version import __version__


class SettingsTab(QWidget):
    check_updates_requested = Signal(dict)

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._build_ui()
        self.state.config_reloaded.connect(self.reload_view)
        self.reload_view()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        update_group = QGroupBox("프로그램 업데이트")
        update_layout = QVBoxLayout(update_group)

        summary_label = QLabel(
            "공개 GitHub Releases를 사용합니다. 설치 파일을 다운로드한 뒤 SHA-256을 검증하고, "
            "사용자가 확인한 경우에만 설치 프로그램을 실행합니다."
        )
        summary_label.setWordWrap(True)
        update_layout.addWidget(summary_label)

        form = QFormLayout()
        self.version_label = QLabel(__version__)
        self.github_repo_edit = QLineEdit()
        self.github_repo_edit.setPlaceholderText("예: your-org/netops-toolkit")
        self.asset_pattern_edit = QLineEdit()
        self.asset_pattern_edit.setPlaceholderText(r"예: NetOpsToolkit-setup.*\.exe$")
        self.check_on_startup_check = QCheckBox("프로그램 시작 시 업데이트 확인")
        self.include_prerelease_check = QCheckBox("사전 배포(prerelease) 포함")

        form.addRow("현재 버전", self.version_label)
        form.addRow("GitHub 저장소", self.github_repo_edit)
        form.addRow("설치 파일 패턴", self.asset_pattern_edit)
        form.addRow("", self.check_on_startup_check)
        form.addRow("", self.include_prerelease_check)
        update_layout.addLayout(form)

        button_row = QHBoxLayout()
        self.save_update_button = QPushButton("업데이트 설정 저장")
        self.check_update_button = QPushButton("업데이트 확인")
        button_row.addWidget(self.save_update_button)
        button_row.addWidget(self.check_update_button)
        button_row.addStretch(1)
        update_layout.addLayout(button_row)

        self.update_status_label = QLabel("저장소를 설정하면 업데이트 확인을 사용할 수 있습니다.")
        self.update_status_label.setWordWrap(True)
        self.update_details = QPlainTextEdit()
        self.update_details.setReadOnly(True)
        self.update_details.setMaximumHeight(180)
        update_layout.addWidget(self.update_status_label)
        update_layout.addWidget(self.update_details)
        layout.addWidget(update_group)

        path_group = QGroupBox("경로")
        path_layout = QVBoxLayout(path_group)
        self.config_dir_label = QLabel()
        self.ip_profile_label = QLabel()
        self.wifi_profile_label = QLabel()
        self.log_dir_label = QLabel()
        path_layout.addWidget(self.config_dir_label)
        path_layout.addWidget(self.ip_profile_label)
        path_layout.addWidget(self.wifi_profile_label)
        path_layout.addWidget(self.log_dir_label)

        folder_button_row = QHBoxLayout()
        self.open_config_button = QPushButton("Config 폴더 열기")
        self.open_logs_button = QPushButton("로그 폴더 열기")
        self.reload_button = QPushButton("디스크에서 다시 불러오기")
        folder_button_row.addWidget(self.open_config_button)
        folder_button_row.addWidget(self.open_logs_button)
        folder_button_row.addWidget(self.reload_button)
        path_layout.addLayout(folder_button_row)
        layout.addWidget(path_group)
        layout.addStretch(1)

        self.open_config_button.clicked.connect(lambda: open_in_explorer(self.state.paths.config_dir))
        self.open_logs_button.clicked.connect(lambda: open_in_explorer(self.state.paths.logs_dir))
        self.reload_button.clicked.connect(self.state.reload_config_files)
        self.save_update_button.clicked.connect(lambda: self.save_update_settings(show_feedback=True))
        self.check_update_button.clicked.connect(self._request_update_check)

    def current_update_config(self) -> dict:
        return {
            "github_repo": self.github_repo_edit.text().strip(),
            "installer_asset_pattern": self.asset_pattern_edit.text().strip() or r"NetOpsToolkit-setup.*\.exe$",
            "check_on_startup": self.check_on_startup_check.isChecked(),
            "include_prerelease": self.include_prerelease_check.isChecked(),
        }

    def save_update_settings(self, show_feedback: bool = False) -> dict:
        config = dict(self.state.app_config)
        config["update"] = self.current_update_config()
        self.state.save_app_config(config)
        if show_feedback:
            self.set_update_status("업데이트 설정을 저장했습니다.")
        return config["update"]

    def set_update_status(self, message: str, details: str = "") -> None:
        self.update_status_label.setText(message)
        if details:
            self.update_details.setPlainText(details)
        elif message:
            self.update_details.clear()

    def set_update_busy(self, busy: bool) -> None:
        self.save_update_button.setEnabled(not busy)
        self.check_update_button.setEnabled(not busy)

    def reload_view(self) -> None:
        update_config = self.state.app_config.get("update", {})
        self.github_repo_edit.setText(str(update_config.get("github_repo", "") or ""))
        self.asset_pattern_edit.setText(
            str(update_config.get("installer_asset_pattern", r"NetOpsToolkit-setup.*\.exe$") or "")
        )
        self.check_on_startup_check.setChecked(bool(update_config.get("check_on_startup", True)))
        self.include_prerelease_check.setChecked(bool(update_config.get("include_prerelease", False)))

        self.config_dir_label.setText(f"Config 폴더: {self.state.paths.config_dir}")
        self.ip_profile_label.setText(f"IP 프로필: {self.state.paths.ip_profiles}")
        self.wifi_profile_label.setText(f"Wi-Fi 프로필: {self.state.paths.wifi_profiles}")
        self.log_dir_label.setText(f"로그 폴더: {self.state.paths.logs_dir}")
        self.version_label.setText(__version__)

        if not self.github_repo_edit.text().strip():
            self.set_update_status("저장소를 설정하면 업데이트 확인을 사용할 수 있습니다.")

    def _request_update_check(self) -> None:
        update_config = self.save_update_settings(show_feedback=False)
        self.check_updates_requested.emit(dict(update_config))
