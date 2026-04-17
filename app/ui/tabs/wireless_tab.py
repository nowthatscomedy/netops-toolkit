from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.app_state import AppState
from app.models.network_models import NearbyAccessPoint, WirelessInfo
from app.models.profile_models import WifiAdvancedProfile
from app.utils.parser import summarize_channels
from app.utils.threading_utils import FunctionWorker


class WirelessTab(QWidget):
    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._active_workers: list[FunctionWorker] = []
        self.previous_info: WirelessInfo | None = None
        self.nearby_access_points: list[NearbyAccessPoint] = []
        self._pending_adapter_name = ""
        self._pending_profile_name = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_wireless_info)
        self.fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        self._build_ui()
        self.state.config_reloaded.connect(self._reload_wifi_profiles)
        self._reload_wifi_profiles()
        self.refresh_wireless_info()
        self.refresh_nearby_access_points()
        self.load_wireless_adapters()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.admin_label = QLabel()
        self.admin_label.setWordWrap(True)
        self._update_admin_banner()
        layout.addWidget(self.admin_label)

        top_row = QHBoxLayout()
        layout.addLayout(top_row, 1)

        status_group = QGroupBox("현재 Wi-Fi 상태")
        status_layout = QVBoxLayout(status_group)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton("새로고침")
        self.auto_refresh_check = QCheckBox("자동 갱신")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 30)
        self.interval_spin.setValue(int(self.state.app_config.get("wireless_refresh_interval_sec", 2)))
        self.interval_spin.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.auto_refresh_check)
        controls.addWidget(QLabel("주기(초)"))
        controls.addWidget(self.interval_spin)
        controls.addStretch(1)
        status_layout.addLayout(controls)

        form = QFormLayout()
        self.info_labels = {
            "interface_name": QLabel("-"),
            "state": QLabel("-"),
            "ssid": QLabel("-"),
            "bssid": QLabel("-"),
            "radio_type": QLabel("-"),
            "channel": QLabel("-"),
            "band": QLabel("-"),
            "signal": QLabel("-"),
            "receive_rate": QLabel("-"),
            "transmit_rate": QLabel("-"),
        }
        form.addRow("어댑터", self.info_labels["interface_name"])
        form.addRow("상태", self.info_labels["state"])
        form.addRow("SSID", self.info_labels["ssid"])
        form.addRow("BSSID", self.info_labels["bssid"])
        form.addRow("무선 규격", self.info_labels["radio_type"])
        form.addRow("채널", self.info_labels["channel"])
        form.addRow("대역", self.info_labels["band"])
        form.addRow("신호", self.info_labels["signal"])
        form.addRow("수신 속도", self.info_labels["receive_rate"])
        form.addRow("송신 속도", self.info_labels["transmit_rate"])
        status_layout.addLayout(form)
        top_row.addWidget(status_group, 2)

        change_group = QGroupBox("연결 변화 로그")
        change_layout = QVBoxLayout(change_group)
        self.change_log = QListWidget()
        change_layout.addWidget(self.change_log)
        top_row.addWidget(change_group, 1)

        nearby_group = QGroupBox("주변 AP / 채널 현황")
        nearby_layout = QVBoxLayout(nearby_group)
        nearby_controls = QHBoxLayout()
        self.nearby_refresh_button = QPushButton("주변 AP 새로고침")
        self.nearby_refresh_oui_button = QPushButton("OUI 캐시 갱신")
        self.nearby_summary_label = QLabel("스캔 전")
        self.nearby_summary_label.setStyleSheet("color:#666;")
        nearby_controls.addWidget(self.nearby_refresh_button)
        nearby_controls.addWidget(self.nearby_refresh_oui_button)
        nearby_controls.addStretch(1)
        nearby_controls.addWidget(self.nearby_summary_label, 2)
        nearby_layout.addLayout(nearby_controls)

        self.nearby_table = QTableWidget(0, 10)
        self.nearby_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.nearby_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.nearby_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.nearby_table.setAlternatingRowColors(True)
        self.nearby_table.setHorizontalHeaderLabels(
            ["SSID", "BSSID", "벤더", "신호", "무선 규격", "대역", "채널", "보안", "채널 사용률", "연결 단말"]
        )
        self.nearby_table.verticalHeader().setVisible(False)
        self.nearby_table.horizontalHeader().setStretchLastSection(True)
        nearby_layout.addWidget(self.nearby_table, 1)
        layout.addWidget(nearby_group, 1)

        bottom_group = QGroupBox("Wi-Fi 고급 설정 프로필")
        bottom_layout = QFormLayout(bottom_group)
        self.adapter_combo = QComboBox()
        self.wifi_profile_combo = QComboBox()
        self.property_output = QPlainTextEdit()
        self.property_output.setReadOnly(True)
        self.property_output.setFont(self.fixed_font)
        self.property_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.profile_result = QPlainTextEdit()
        self.profile_result.setReadOnly(True)
        self.profile_result.setMaximumHeight(120)
        self.profile_result.setFont(self.fixed_font)
        self.profile_result.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        buttons = QHBoxLayout()
        self.refresh_adapters_button = QPushButton("어댑터 새로고침")
        self.load_properties_button = QPushButton("현재값 조회")
        self.apply_profile_button = QPushButton("프로필 적용")
        buttons.addWidget(self.refresh_adapters_button)
        buttons.addWidget(self.load_properties_button)
        buttons.addWidget(self.apply_profile_button)
        bottom_layout.addRow("어댑터", self.adapter_combo)
        bottom_layout.addRow("프로필", self.wifi_profile_combo)
        bottom_layout.addRow("", buttons)
        bottom_layout.addRow("현재 속성", self.property_output)
        bottom_layout.addRow("적용 결과", self.profile_result)
        layout.addWidget(bottom_group, 1)

        self.refresh_button.clicked.connect(self.refresh_wireless_info)
        self.auto_refresh_check.toggled.connect(self._toggle_auto_refresh)
        self.interval_spin.valueChanged.connect(self._handle_interval_change)
        self.nearby_refresh_button.clicked.connect(self.refresh_nearby_access_points)
        self.nearby_refresh_oui_button.clicked.connect(self.refresh_nearby_oui_cache)
        self.refresh_adapters_button.clicked.connect(self.load_wireless_adapters)
        self.load_properties_button.clicked.connect(self.load_adapter_properties)
        self.apply_profile_button.clicked.connect(self.apply_wifi_profile)

    def _update_admin_banner(self) -> None:
        if self.state.is_admin:
            self.admin_label.setText("관리자 권한으로 실행 중입니다. Wi-Fi 고급 속성 프로필을 적용할 수 있습니다.")
            self.admin_label.setStyleSheet("background:#e8f5e9; color:#1b5e20; padding:8px; border:1px solid #a5d6a7;")
        else:
            self.admin_label.setText("현재 상태 조회는 가능하지만, Wi-Fi 고급 속성 적용에는 관리자 권한이 필요합니다.")
            self.admin_label.setStyleSheet("background:#fff8e1; color:#8d6e00; padding:8px; border:1px solid #ffe082;")

    def _reload_wifi_profiles(self) -> None:
        self.wifi_profile_combo.clear()
        for profile in self.state.wifi_profiles:
            self.wifi_profile_combo.addItem(profile.name)
        if self._pending_profile_name:
            index = self.wifi_profile_combo.findText(self._pending_profile_name)
            if index >= 0:
                self.wifi_profile_combo.setCurrentIndex(index)
                self._pending_profile_name = ""

    def refresh_wireless_info(self) -> None:
        self._start_worker(
            self.state.wireless_service.get_wireless_info,
            on_result=self._update_wireless_view,
            error_title="무선 상태 조회 실패",
        )

    def refresh_nearby_access_points(self) -> None:
        self.nearby_summary_label.setText("주변 AP를 스캔하는 중...")
        self._start_worker(
            self.state.wireless_service.scan_nearby_access_points,
            on_result=self._update_nearby_access_points,
            error_title="주변 AP 조회 실패",
        )

    def refresh_nearby_oui_cache(self) -> None:
        self.nearby_summary_label.setText("OUI 캐시를 갱신하는 중...")
        self._start_worker(
            self.state.oui_service.refresh_cache,
            on_result=self._finish_nearby_oui_refresh,
            error_title="OUI 캐시 갱신 실패",
        )

    def _update_wireless_view(self, info: WirelessInfo) -> None:
        self.info_labels["interface_name"].setText(info.interface_name or info.description or "-")
        self.info_labels["interface_name"].setToolTip(info.description or info.interface_name or "")
        self.info_labels["state"].setText(info.state or "-")
        self.info_labels["ssid"].setText(info.ssid or "-")
        self.info_labels["bssid"].setText(info.bssid or "-")
        self.info_labels["radio_type"].setText(info.radio_type or "-")
        self.info_labels["channel"].setText(info.channel or "-")
        self.info_labels["band"].setText(info.band or "-")
        self.info_labels["signal"].setText(info.signal_text)
        self.info_labels["receive_rate"].setText(f"{info.receive_rate_mbps} Mbps" if info.receive_rate_mbps else "-")
        self.info_labels["transmit_rate"].setText(f"{info.transmit_rate_mbps} Mbps" if info.transmit_rate_mbps else "-")

        state_lower = info.state.lower()
        state_color = "#1b5e20" if ("connected" in state_lower or "연결" in info.state) else "#b71c1c"
        self.info_labels["state"].setStyleSheet(f"color:{state_color}; font-weight:bold;")
        self._log_wireless_changes(info)
        self.previous_info = info

    def _update_nearby_access_points(self, access_points: list[NearbyAccessPoint]) -> None:
        self.nearby_access_points = access_points
        self.nearby_table.setRowCount(0)

        for access_point in access_points:
            row = self.nearby_table.rowCount()
            self.nearby_table.insertRow(row)
            security = " / ".join(part for part in [access_point.authentication, access_point.encryption] if part) or "-"
            values = [
                access_point.ssid or "-",
                access_point.bssid or "-",
                access_point.vendor or "-",
                access_point.signal_text,
                access_point.radio_standard or "-",
                access_point.band or "-",
                access_point.channel or "-",
                security,
                (
                    f"{access_point.channel_utilization_percent}%"
                    if access_point.channel_utilization_percent is not None
                    else "-"
                ),
                str(access_point.connected_stations) if access_point.connected_stations is not None else "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3 and access_point.signal_percent is not None:
                    if access_point.signal_percent >= 70:
                        item.setForeground(QColor("#1b5e20"))
                    elif access_point.signal_percent >= 40:
                        item.setForeground(QColor("#ef6c00"))
                    else:
                        item.setForeground(QColor("#b71c1c"))
                self.nearby_table.setItem(row, column, item)

        summary = summarize_channels(access_points)
        count_text = f"AP {len(access_points)}개"
        cache_text = self.state.oui_service.cache_summary()
        self.nearby_summary_label.setText(f"{count_text} | {summary} | {cache_text}")

    def _finish_nearby_oui_refresh(self, result) -> None:
        if result.success:
            self.refresh_nearby_access_points()
            return
        self.nearby_summary_label.setText(result.message)

    def _log_wireless_changes(self, current: WirelessInfo) -> None:
        if not self.previous_info:
            self._append_change_log(f"초기 상태: {current.state} / SSID={current.ssid or '-'}")
            return

        previous = self.previous_info
        if previous.state != current.state:
            self._append_change_log(f"상태 변경: {previous.state or '-'} -> {current.state or '-'}", QColor("#b71c1c"))
        if previous.ssid != current.ssid:
            self._append_change_log(f"SSID 변경: {previous.ssid or '-'} -> {current.ssid or '-'}", QColor("#ef6c00"))
        if previous.bssid != current.bssid:
            self._append_change_log(f"BSSID 변경: {previous.bssid or '-'} -> {current.bssid or '-'}", QColor("#ef6c00"))
        if previous.channel != current.channel:
            self._append_change_log(f"채널 변경: {previous.channel or '-'} -> {current.channel or '-'}", QColor("#ef6c00"))
        if previous.signal_percent is not None and current.signal_percent is not None and previous.signal_percent - current.signal_percent >= 15:
            self._append_change_log(f"신호 저하: {previous.signal_percent}% -> {current.signal_percent}%", QColor("#b71c1c"))

    def _append_change_log(self, message: str, color: QColor | None = None) -> None:
        item = QListWidgetItem(message)
        if color:
            item.setForeground(color)
        self.change_log.insertItem(0, item)

    def _toggle_auto_refresh(self, enabled: bool) -> None:
        if enabled:
            self.timer.start(self.interval_spin.value() * 1000)
        else:
            self.timer.stop()

    def _handle_interval_change(self, value: int) -> None:
        if self.auto_refresh_check.isChecked():
            self.timer.start(value * 1000)

    def load_wireless_adapters(self) -> None:
        self._start_worker(
            self.state.wireless_service.list_wireless_adapters,
            on_result=self._populate_adapter_combo,
            error_title="무선 어댑터 목록 조회 실패",
        )

    def _populate_adapter_combo(self, adapters: list[str]) -> None:
        self.adapter_combo.clear()
        self.adapter_combo.addItems(adapters)
        if self._pending_adapter_name:
            index = self.adapter_combo.findText(self._pending_adapter_name)
            if index >= 0:
                self.adapter_combo.setCurrentIndex(index)
                self._pending_adapter_name = ""

    def load_adapter_properties(self) -> None:
        adapter = self.adapter_combo.currentText().strip()
        if not adapter:
            QMessageBox.warning(self, "선택 필요", "무선 어댑터를 먼저 선택해 주세요.")
            return
        self.property_output.setPlainText("어댑터 속성 조회 중...")
        self._start_worker(
            self.state.wifi_profile_service.get_advanced_properties,
            adapter,
            on_result=lambda properties: self.property_output.setPlainText(
                self.state.wifi_profile_service.format_properties(properties)
            ),
            error_title="속성 조회 실패",
        )

    def apply_wifi_profile(self) -> None:
        adapter = self.adapter_combo.currentText().strip()
        profile = self._selected_wifi_profile()
        if not adapter or not profile:
            QMessageBox.warning(self, "선택 필요", "어댑터와 프로필을 모두 선택해 주세요.")
            return
        if not self.state.is_admin:
            QMessageBox.warning(self, "관리자 권한 필요", "Wi-Fi 고급 속성 적용은 관리자 권한이 필요합니다.")
            return
        self.profile_result.setPlainText("프로필 적용 중...")
        self._start_worker(
            self.state.wifi_profile_service.apply_profile,
            adapter,
            profile,
            on_result=lambda result: self.profile_result.setPlainText(result.message + ("\n\n" + result.details if result.details else "")),
            on_finished=self.load_adapter_properties,
            error_title="프로필 적용 실패",
        )

    def _selected_wifi_profile(self) -> WifiAdvancedProfile | None:
        index = self.wifi_profile_combo.currentIndex()
        if index < 0 or index >= len(self.state.wifi_profiles):
            return None
        return self.state.wifi_profiles[index]

    def save_ui_state(self) -> dict:
        profile = self._selected_wifi_profile()
        return {
            "auto_refresh": self.auto_refresh_check.isChecked(),
            "interval_sec": self.interval_spin.value(),
            "selected_adapter": self.adapter_combo.currentText().strip(),
            "selected_profile": profile.name if profile else self.wifi_profile_combo.currentText().strip(),
        }

    def restore_ui_state(self, ui_state: dict | None) -> None:
        state = dict(ui_state or {})
        if not state:
            return

        interval_sec = int(state.get("interval_sec", self.interval_spin.value()) or self.interval_spin.value())
        self.interval_spin.setValue(max(1, min(30, interval_sec)))

        self._pending_adapter_name = str(state.get("selected_adapter", "") or "").strip()
        self._pending_profile_name = str(state.get("selected_profile", "") or "").strip()

        if self._pending_profile_name:
            index = self.wifi_profile_combo.findText(self._pending_profile_name)
            if index >= 0:
                self.wifi_profile_combo.setCurrentIndex(index)
                self._pending_profile_name = ""

        if self._pending_adapter_name:
            index = self.adapter_combo.findText(self._pending_adapter_name)
            if index >= 0:
                self.adapter_combo.setCurrentIndex(index)
                self._pending_adapter_name = ""

        self.auto_refresh_check.setChecked(bool(state.get("auto_refresh", False)))

    def _start_worker(
        self,
        fn: Callable,
        *args,
        on_result: Callable | None = None,
        on_progress: Callable | None = None,
        on_finished: Callable | None = None,
        error_title: str = "작업 실패",
        **kwargs,
    ) -> None:
        worker = FunctionWorker(fn, *args, **kwargs)
        self._active_workers.append(worker)
        if on_result:
            worker.signals.result.connect(on_result)
        if on_progress:
            worker.signals.progress.connect(on_progress)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(lambda text: QMessageBox.warning(self, error_title, text))
        worker.signals.finished.connect(lambda worker=worker: self._discard_worker(worker))
        self.state.thread_pool.start(worker)

    def _discard_worker(self, worker: FunctionWorker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
