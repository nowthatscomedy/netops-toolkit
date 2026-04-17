from __future__ import annotations

import csv
import re
from datetime import datetime
from threading import Event
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from app.app_state import AppState
from app.models.result_models import OperationResult, PingResult, TcpCheckResult
from app.utils.file_utils import timestamped_export_path
from app.utils.threading_utils import FunctionWorker
from app.utils.validators import ValidationError, parse_positive_int, validate_host_input


class ResultDockWidget(QDockWidget):
    def __init__(self, title: str, on_restore, parent=None) -> None:
        super().__init__(title, parent)
        self._on_restore = on_restore
        self._closing_from_restore = False

    def closeEvent(self, event) -> None:
        if not self._closing_from_restore and self._on_restore is not None:
            self._on_restore(from_dock_close=True)
        super().closeEvent(event)


class DiagnosticsTab(QWidget):
    result_dock_visibility_changed = Signal(str, bool)

    DNS_TYPES = [
        ("A - IPv4 주소", "A", "도메인의 IPv4 주소를 조회합니다."),
        ("AAAA - IPv6 주소", "AAAA", "도메인의 IPv6 주소를 조회합니다."),
        ("CNAME - 별칭", "CNAME", "도메인이 연결된 별칭 레코드를 조회합니다."),
        ("MX - 메일 서버", "MX", "메일 서버 레코드를 조회합니다."),
        ("PTR - 역방향 조회", "PTR", "IP 주소를 도메인 이름으로 조회합니다."),
    ]

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._active_workers: list[FunctionWorker] = []
        self._floating_result_docks: dict[str, ResultDockWidget | None] = {"ping": None, "tcp": None}
        self._result_hosts: dict[str, QWidget] = {}
        self._result_host_layouts: dict[str, QVBoxLayout] = {}
        self._result_panels: dict[str, QWidget] = {}
        self._result_placeholders: dict[str, QLabel] = {}
        self._result_splitters: dict[str, QSplitter] = {}

        self.ping_results: list[PingResult] = []
        self.tcp_results: list[TcpCheckResult] = []
        self.ping_cancel_event: Event | None = None
        self.tcp_cancel_event: Event | None = None
        self.trace_cancel_event: Event | None = None
        self.iperf_cancel_event: Event | None = None

        self.ping_row_map: dict[tuple[str, str], int] = {}
        self.tcp_row_map: dict[tuple[str, str, int], int] = {}
        self.ping_log_lines: dict[tuple[str, str], list[str]] = {}
        self.tcp_log_lines: dict[tuple[str, str, int], list[str]] = {}

        self.fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._build_tools_tab(), "네트워크 도구")
        self.tab_widget.addTab(self._build_ping_tab(), "Ping")
        self.tab_widget.addTab(self._build_tcp_tab(), "TCPing")
        self.tab_widget.addTab(self._build_dns_tab(), "nslookup")
        self.tab_widget.addTab(self._build_trace_tab(), "tracert / pathping")
        self.tab_widget.addTab(self._build_iperf_tab(), "iperf3")
        layout.addWidget(self.tab_widget)

    def _build_ping_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("멀티 Ping")
        form = QFormLayout(group)
        self.ping_targets_edit = QPlainTextEdit()
        self.ping_targets_edit.setMaximumHeight(110)
        self.ping_targets_edit.setPlaceholderText("예:\nGW,192.168.0.1\nDNS,8.8.8.8")
        self.ping_count_edit = QLineEdit()
        self.ping_count_edit.setPlaceholderText(str(int(self.state.app_config.get("default_ping_count", 4))))
        self.ping_timeout_edit = QLineEdit()
        self.ping_timeout_edit.setPlaceholderText(str(int(self.state.app_config.get("default_ping_timeout_ms", 4000))))
        self.ping_workers_edit = QLineEdit()
        self.ping_workers_edit.setPlaceholderText(str(int(self.state.app_config.get("default_ping_workers", 8))))
        self.ping_continuous_check = QCheckBox("연속 실행 (-t)")

        button_row = QHBoxLayout()
        self.ping_start_button = QPushButton("실행")
        self.ping_cancel_button = QPushButton("중지")
        self.ping_cancel_button.setEnabled(False)
        button_row.addWidget(self.ping_start_button)
        button_row.addWidget(self.ping_cancel_button)
        button_row.addStretch(1)

        form.addRow("대상", self.ping_targets_edit)
        form.addRow("횟수", self.ping_count_edit)
        form.addRow("Timeout (ms)", self.ping_timeout_edit)
        form.addRow("동시 실행 수", self.ping_workers_edit)
        form.addRow("", self.ping_continuous_check)
        form.addRow("", button_row)
        layout.addWidget(group)

        self.ping_table = QTableWidget(0, 11)
        self.ping_table.setHorizontalHeaderLabels(
            ["이름", "대상", "상태", "전송", "수신", "실패", "손실률", "최소(ms)", "평균(ms)", "최대(ms)", "최근 시각"]
        )
        self._setup_table(self.ping_table)

        self.ping_log = self._output()
        self.ping_log_panel = self._build_log_panel("실시간 로그", self.ping_log)
        self.ping_splitter = self._build_result_splitter(
            key="ping",
            table=self.ping_table,
            log_panel=self.ping_log_panel,
        )
        layout.addWidget(self.ping_splitter, 1)

        self.ping_start_button.clicked.connect(self.start_ping)
        self.ping_cancel_button.clicked.connect(self.cancel_ping)
        self.ping_continuous_check.toggled.connect(lambda checked: self.ping_count_edit.setEnabled(not checked))
        return page

    def _build_tcp_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("TCPing")
        form = QFormLayout(group)
        self.tcp_targets_edit = QPlainTextEdit()
        self.tcp_targets_edit.setMaximumHeight(110)
        self.tcp_targets_edit.setPlaceholderText("예:\nDNS,8.8.8.8\nGW,192.168.0.1")
        self.tcp_ports_edit = QLineEdit()
        self.tcp_ports_edit.setPlaceholderText("예: 22,80,443 또는 1-1024,2022")
        self.tcp_count_edit = QLineEdit()
        self.tcp_count_edit.setPlaceholderText("4")
        self.tcp_timeout_edit = QLineEdit()
        self.tcp_timeout_edit.setPlaceholderText(str(int(self.state.app_config.get("default_tcp_timeout_ms", 1000))))
        self.tcp_workers_edit = QLineEdit()
        self.tcp_workers_edit.setPlaceholderText(str(int(self.state.app_config.get("default_tcp_workers", 32))))
        self.tcp_continuous_check = QCheckBox("연속 실행 (-t)")

        button_row = QHBoxLayout()
        self.tcp_start_button = QPushButton("실행")
        self.tcp_cancel_button = QPushButton("중지")
        self.tcp_cancel_button.setEnabled(False)
        button_row.addWidget(self.tcp_start_button)
        button_row.addWidget(self.tcp_cancel_button)
        button_row.addStretch(1)

        form.addRow("대상", self.tcp_targets_edit)
        form.addRow("포트", self.tcp_ports_edit)
        form.addRow("횟수", self.tcp_count_edit)
        form.addRow("Timeout (ms)", self.tcp_timeout_edit)
        form.addRow("동시 실행 수", self.tcp_workers_edit)
        form.addRow("", self.tcp_continuous_check)
        form.addRow("", button_row)
        layout.addWidget(group)

        self.tcp_table = QTableWidget(0, 12)
        self.tcp_table.setHorizontalHeaderLabels(
            ["대상", "포트", "상태", "시도", "성공", "실패", "손실률", "최소(ms)", "평균(ms)", "최대(ms)", "최근 시각"]
        )
        self._setup_table(self.tcp_table)
        self.tcp_table.setHorizontalHeaderLabels(
            ["이름", "대상", "포트", "상태", "시도", "성공", "실패", "손실률", "최소(ms)", "평균(ms)", "최대(ms)", "최근 시각"]
        )

        self.tcp_log = self._output()
        self.tcp_log_panel = self._build_log_panel("실시간 로그", self.tcp_log)
        self.tcp_splitter = self._build_result_splitter(
            key="tcp",
            table=self.tcp_table,
            log_panel=self.tcp_log_panel,
        )
        layout.addWidget(self.tcp_splitter, 1)

        self.tcp_start_button.clicked.connect(self.start_tcp_check)
        self.tcp_cancel_button.clicked.connect(self.cancel_tcp_check)
        self.tcp_continuous_check.toggled.connect(lambda checked: self.tcp_count_edit.setEnabled(not checked))
        return page

    def _build_dns_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("nslookup")
        form = QFormLayout(group)
        self.dns_query_edit = QLineEdit()
        self.dns_query_edit.setPlaceholderText("예: google.com 또는 8.8.8.8")
        self.dns_type_combo = QComboBox()
        for label, value, description in self.DNS_TYPES:
            self.dns_type_combo.addItem(label, (value, description))
        self.dns_type_hint = QLabel()
        self.dns_type_hint.setStyleSheet("color:#555;")
        self._update_dns_type_hint()
        self.dns_server_edit = QLineEdit()
        self.dns_server_edit.setPlaceholderText("예: 8.8.8.8")
        self.dns_run_button = QPushButton("조회")

        form.addRow("도메인 / IP", self.dns_query_edit)
        form.addRow("레코드 타입", self.dns_type_combo)
        form.addRow("", self.dns_type_hint)
        form.addRow("DNS 서버", self.dns_server_edit)
        form.addRow("", self.dns_run_button)
        layout.addWidget(group)

        self.dns_output = self._output()
        layout.addWidget(self.dns_output, 1)

        self.dns_type_combo.currentIndexChanged.connect(self._update_dns_type_hint)
        self.dns_run_button.clicked.connect(self.run_dns_lookup)
        return page

    def _build_trace_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("경로 추적")
        form = QFormLayout(group)
        self.trace_target_edit = QLineEdit()
        self.trace_target_edit.setPlaceholderText("예: 8.8.8.8")
        self.trace_no_resolve_check = QCheckBox("호스트 이름 해석 안 함 (-d / -n)")

        button_row = QHBoxLayout()
        self.tracert_button = QPushButton("tracert 실행")
        self.pathping_button = QPushButton("pathping 실행")
        self.trace_cancel_button = QPushButton("중지")
        self.trace_cancel_button.setEnabled(False)
        button_row.addWidget(self.tracert_button)
        button_row.addWidget(self.pathping_button)
        button_row.addWidget(self.trace_cancel_button)
        button_row.addStretch(1)

        form.addRow("대상", self.trace_target_edit)
        form.addRow("", self.trace_no_resolve_check)
        form.addRow("", button_row)
        layout.addWidget(group)

        self.trace_status_label = QLabel("준비")
        layout.addWidget(self.trace_status_label)
        self.trace_output = self._output()
        layout.addWidget(self.trace_output, 1)

        self.tracert_button.clicked.connect(lambda: self.start_trace("tracert"))
        self.pathping_button.clicked.connect(lambda: self.start_trace("pathping"))
        self.trace_cancel_button.clicked.connect(self.cancel_trace)
        return page

    def _build_tools_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        button_row = QHBoxLayout()
        self.snapshot_button = QPushButton("현재 인터페이스")
        self.ipconfig_button = QPushButton("ipconfig /all")
        self.route_button = QPushButton("route print")
        self.arp_button = QPushButton("arp -a")
        self.flush_dns_button = QPushButton("DNS 캐시 비우기")
        for button in [
            self.snapshot_button,
            self.ipconfig_button,
            self.route_button,
            self.arp_button,
            self.flush_dns_button,
        ]:
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.tools_output = self._output()
        layout.addWidget(self.tools_output, 1)

        self.snapshot_button.clicked.connect(self.load_interface_snapshot)
        self.ipconfig_button.clicked.connect(lambda: self._run_tools_command(self.state.trace_service.run_ipconfig_all))
        self.route_button.clicked.connect(lambda: self._run_tools_command(self.state.trace_service.run_route_print))
        self.arp_button.clicked.connect(lambda: self._run_tools_command(self.state.trace_service.run_arp_table))
        self.flush_dns_button.clicked.connect(
            lambda: self._run_tools_command(self.state.dns_service.flush_dns_cache)
        )
        return page

    def _build_iperf_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("iperf3")
        form = QFormLayout(group)
        self.iperf_mode_combo = QComboBox()
        self.iperf_mode_combo.addItem("클라이언트", "client")
        self.iperf_mode_combo.addItem("서버", "server")
        self.iperf_server_edit = QLineEdit()
        self.iperf_server_edit.setPlaceholderText("예: 192.168.0.10")
        self.iperf_port_edit = QLineEdit()
        self.iperf_port_edit.setPlaceholderText("5201")
        self.iperf_streams_edit = QLineEdit()
        self.iperf_streams_edit.setPlaceholderText("1")
        self.iperf_duration_edit = QLineEdit()
        self.iperf_duration_edit.setPlaceholderText("10")
        self.iperf_reverse_check = QCheckBox("Reverse (-R)")

        button_row = QHBoxLayout()
        self.iperf_run_button = QPushButton("실행")
        self.iperf_cancel_button = QPushButton("중지")
        self.iperf_cancel_button.setEnabled(False)
        button_row.addWidget(self.iperf_run_button)
        button_row.addWidget(self.iperf_cancel_button)
        button_row.addStretch(1)

        form.addRow("모드", self.iperf_mode_combo)
        form.addRow("서버", self.iperf_server_edit)
        form.addRow("포트", self.iperf_port_edit)
        form.addRow("스트림 수", self.iperf_streams_edit)
        form.addRow("지속 시간(초)", self.iperf_duration_edit)
        form.addRow("", self.iperf_reverse_check)
        form.addRow("", button_row)
        layout.addWidget(group)

        self.iperf_output = self._output()
        layout.addWidget(self.iperf_output, 1)

        self.iperf_mode_combo.currentIndexChanged.connect(self._update_iperf_mode_state)
        self.iperf_run_button.clicked.connect(self.run_iperf_test)
        self.iperf_cancel_button.clicked.connect(self.cancel_iperf_test)
        self._update_iperf_mode_state()
        return page

    def _setup_table(self, table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

    def _output(self) -> QPlainTextEdit:
        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setFont(self.fixed_font)
        output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return output

    def _build_log_panel(self, title: str, output: QPlainTextEdit) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(title))
        layout.addWidget(output)
        return panel

    def _build_result_splitter(
        self,
        key: str,
        table: QTableWidget,
        log_panel: QWidget,
    ) -> QSplitter:
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        result_host = QWidget()
        result_host_layout = QVBoxLayout(result_host)
        result_host_layout.setContentsMargins(0, 0, 0, 0)

        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(table, 1)

        button_row = QHBoxLayout()
        csv_button = QPushButton("전체 표 CSV 저장")
        log_button = QPushButton("선택 항목 로그 저장")
        button_row.addWidget(csv_button)
        button_row.addWidget(log_button)
        button_row.addStretch(1)
        result_layout.addLayout(button_row)

        placeholder = QLabel("결과 표가 분리되어 있습니다. 상단 `보기` 메뉴에서 다시 전환할 수 있습니다.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color:#666; padding:6px 10px; border:1px dashed #bbb;")
        placeholder.setMaximumHeight(34)
        placeholder.hide()

        self._result_hosts[key] = result_host
        result_host_layout.addWidget(result_panel)
        result_host_layout.addWidget(placeholder)

        self._result_host_layouts[key] = result_host_layout
        self._result_panels[key] = result_panel
        self._result_placeholders[key] = placeholder
        self._result_splitters[key] = splitter

        if key == "ping":
            self.ping_csv_button = csv_button
            self.ping_log_export_button = log_button
            self.ping_csv_button.clicked.connect(lambda: self._export_table_to_csv(self.ping_table, "ping_results"))
            self.ping_log_export_button.clicked.connect(self.export_selected_ping_logs)
        else:
            self.tcp_csv_button = csv_button
            self.tcp_log_export_button = log_button
            self.tcp_csv_button.clicked.connect(lambda: self._export_table_to_csv(self.tcp_table, "tcp_results"))
            self.tcp_log_export_button.clicked.connect(self.export_selected_tcp_logs)

        splitter.addWidget(result_host)
        splitter.addWidget(log_panel)
        splitter.setSizes([430, 170])
        return splitter

    def _detach_result_panel(self, key: str) -> None:
        main_window = self.window()
        if not isinstance(main_window, QMainWindow):
            QMessageBox.warning(self, "분리 실패", "메인 창을 찾지 못해 결과 표를 분리할 수 없습니다.")
            return

        panel = self._result_panels[key]
        result_host = self._result_hosts[key]
        host_layout = self._result_host_layouts[key]
        placeholder = self._result_placeholders[key]

        host_layout.removeWidget(panel)
        panel.setParent(None)
        placeholder.show()
        result_host.setMaximumHeight(40)

        window_title = "Ping 결과 표" if key == "ping" else "TCPing 결과 표"
        dock = ResultDockWidget(
            window_title,
            lambda from_dock_close=False, mode=key: self._attach_result_panel(mode, from_dock_close),
            main_window,
        )
        dock.setObjectName(f"{key}_result_dock")
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )
        dock.setMinimumHeight(180)
        dock.setWidget(panel)
        main_window.addDockWidget(Qt.BottomDockWidgetArea, dock)
        if hasattr(main_window, "log_dock"):
            try:
                main_window.tabifyDockWidget(main_window.log_dock, dock)
            except Exception:
                pass
        dock.show()
        dock.raise_()
        self._floating_result_docks[key] = dock
        self._result_splitters[key].setSizes([40, 200])
        self.result_dock_visibility_changed.emit(key, True)

    def _attach_result_panel(self, key: str, from_dock_close: bool = False) -> None:
        result_host = self._result_hosts[key]
        host_layout = self._result_host_layouts[key]
        panel = self._result_panels[key]
        placeholder = self._result_placeholders[key]
        dock = self._floating_result_docks.get(key)

        if dock is not None:
            current_widget = dock.widget()
            if current_widget is not None and current_widget is not panel:
                panel = current_widget
                self._result_panels[key] = panel
            if current_widget is not None:
                current_widget.setParent(None)
            dock._closing_from_restore = True
            if not from_dock_close:
                dock.close()
            dock.deleteLater()
            self._floating_result_docks[key] = None

        placeholder.hide()
        result_host.setMaximumHeight(16777215)
        host_layout.insertWidget(0, panel)
        panel.show()
        self._result_splitters[key].setSizes([430, 170])
        self.result_dock_visibility_changed.emit(key, False)

    def set_result_dock_visible(self, key: str, visible: bool) -> None:
        if visible:
            if self._floating_result_docks.get(key) is None:
                self._detach_result_panel(key)
            else:
                dock = self._floating_result_docks[key]
                if dock is not None:
                    dock.show()
                    dock.raise_()
            return
        if self._floating_result_docks.get(key) is not None:
            self._attach_result_panel(key)

    def is_result_dock_visible(self, key: str) -> bool:
        return self._floating_result_docks.get(key) is not None

    def _positive_int_or_default(
        self,
        edit: QLineEdit,
        label: str,
        default: int,
        minimum: int = 1,
        maximum: int | None = None,
    ) -> int:
        text = edit.text().strip()
        if not text:
            return default
        return parse_positive_int(text, label, minimum=minimum, maximum=maximum)

    def start_ping(self) -> None:
        try:
            count = self._positive_int_or_default(
                self.ping_count_edit,
                "Ping 횟수",
                int(self.state.app_config.get("default_ping_count", 4)),
            )
            timeout_ms = self._positive_int_or_default(
                self.ping_timeout_edit,
                "Ping Timeout",
                int(self.state.app_config.get("default_ping_timeout_ms", 4000)),
            )
            workers = self._positive_int_or_default(
                self.ping_workers_edit,
                "동시 실행 수",
                int(self.state.app_config.get("default_ping_workers", 8)),
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return

        self.ping_results = []
        self.ping_row_map.clear()
        self.ping_log_lines.clear()
        self.ping_table.setRowCount(0)
        self.ping_log.clear()
        self.ping_cancel_event = Event()
        self._set_ping_running(True)

        self._start_worker(
            self.state.ping_service.run_multi_ping,
            self.ping_targets_edit.toPlainText(),
            count,
            timeout_ms,
            workers,
            self.ping_continuous_check.isChecked(),
            cancel_event=self.ping_cancel_event,
            on_progress=self._handle_ping_progress,
            on_result=self._finish_ping,
            on_finished=lambda: self._set_ping_running(False),
            error_title="Ping 실행 실패",
        )

    def _handle_ping_progress(self, event: dict) -> None:
        result: PingResult = event["result"]
        line = event["line"]
        key = (result.name, result.target)
        self.ping_log.appendPlainText(line)
        self.ping_log_lines.setdefault(key, []).append(line)

        row = self.ping_row_map.get(key)
        if row is None:
            row = self.ping_table.rowCount()
            self.ping_table.insertRow(row)
            self.ping_row_map[key] = row

        values = [
            result.name,
            result.target,
            result.status,
            str(result.sent),
            str(result.received),
            str(max(result.sent - result.received, 0)),
            f"{result.packet_loss:.0f}%",
            f"{result.min_rtt:.1f}" if result.min_rtt is not None else "-",
            f"{result.avg_rtt:.1f}" if result.avg_rtt is not None else "-",
            f"{result.max_rtt:.1f}" if result.max_rtt is not None else "-",
            result.last_seen or "-",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 3:
                if result.status == "정상":
                    item.setForeground(QColor("#1b5e20"))
                elif result.status in ("일부 손실", "시간 초과"):
                    item.setForeground(QColor("#ef6c00"))
                else:
                    item.setForeground(QColor("#b71c1c"))
            self.ping_table.setItem(row, column, item)

    def _finish_ping(self, results: list[PingResult]) -> None:
        self.ping_results = results

    def _set_ping_running(self, running: bool) -> None:
        self.ping_start_button.setEnabled(not running)
        self.ping_cancel_button.setEnabled(running)

    def cancel_ping(self) -> None:
        if self.ping_cancel_event:
            self.ping_cancel_event.set()

    def start_tcp_check(self) -> None:
        try:
            count = self._positive_int_or_default(self.tcp_count_edit, "TCP 횟수", 4)
            timeout_ms = self._positive_int_or_default(
                self.tcp_timeout_edit,
                "TCP Timeout",
                int(self.state.app_config.get("default_tcp_timeout_ms", 1000)),
            )
            workers = self._positive_int_or_default(
                self.tcp_workers_edit,
                "동시 실행 수",
                int(self.state.app_config.get("default_tcp_workers", 32)),
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return

        self.tcp_results = []
        self.tcp_row_map.clear()
        self.tcp_log_lines.clear()
        self.tcp_table.setRowCount(0)
        self.tcp_log.clear()
        self.tcp_cancel_event = Event()
        self._set_tcp_running(True)

        self._start_worker(
            self.state.tcp_check_service.run_multi_check,
            self.tcp_targets_edit.toPlainText(),
            self.tcp_ports_edit.text(),
            count,
            timeout_ms,
            workers,
            self.tcp_continuous_check.isChecked(),
            cancel_event=self.tcp_cancel_event,
            on_progress=self._handle_tcp_progress,
            on_result=self._finish_tcp,
            on_finished=lambda: self._set_tcp_running(False),
            error_title="TCPing 실행 실패",
        )

    def _handle_tcp_progress(self, event: dict) -> None:
        result: TcpCheckResult = event["result"]
        line = event["line"]
        key = (result.name, result.target, result.port)
        self.tcp_log.appendPlainText(line)
        self.tcp_log_lines.setdefault(key, []).append(line)

        row = self.tcp_row_map.get(key)
        if row is None:
            row = self.tcp_table.rowCount()
            self.tcp_table.insertRow(row)
            self.tcp_row_map[key] = row

        values = [
            result.name,
            result.target,
            str(result.port),
            result.status,
            str(result.sent),
            str(result.successful),
            str(result.failed),
            f"{result.packet_loss:.0f}%",
            f"{result.min_response_ms:.2f}" if result.min_response_ms is not None else "-",
            f"{result.response_ms:.2f}" if result.response_ms is not None else "-",
            f"{result.max_response_ms:.2f}" if result.max_response_ms is not None else "-",
            result.last_seen or "-",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 3:
                if result.status == "열림":
                    item.setForeground(QColor("#1b5e20"))
                elif result.status == "부분 응답":
                    item.setForeground(QColor("#ef6c00"))
                else:
                    item.setForeground(QColor("#b71c1c"))
            self.tcp_table.setItem(row, column, item)

    def _finish_tcp(self, results: list[TcpCheckResult]) -> None:
        self.tcp_results = results

    def _set_tcp_running(self, running: bool) -> None:
        self.tcp_start_button.setEnabled(not running)
        self.tcp_cancel_button.setEnabled(running)

    def cancel_tcp_check(self) -> None:
        if self.tcp_cancel_event:
            self.tcp_cancel_event.set()

    def _update_dns_type_hint(self) -> None:
        _value, description = self.dns_type_combo.currentData()
        self.dns_type_hint.setText(description)

    def run_dns_lookup(self) -> None:
        query = self.dns_query_edit.text().strip()
        if not query:
            QMessageBox.warning(self, "입력 확인", "도메인 또는 IP를 입력해 주세요.")
            return

        record_type, _description = self.dns_type_combo.currentData()
        self.dns_output.setPlainText("nslookup 실행 중...")
        self._start_worker(
            self.state.dns_service.lookup,
            query,
            record_type,
            self.dns_server_edit.text().strip(),
            on_result=lambda result: self.dns_output.setPlainText(result.details or result.message),
            error_title="nslookup 실패",
        )

    def start_trace(self, mode: str) -> None:
        try:
            target = validate_host_input(self.trace_target_edit.text())
        except ValidationError as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return

        self.trace_output.clear()
        self.trace_status_label.setText(f"{mode} 실행 중...")
        self.trace_cancel_event = Event()
        self._set_trace_running(True)

        runner = self.state.trace_service.run_tracert if mode == "tracert" else self.state.trace_service.run_pathping
        self._start_worker(
            runner,
            target,
            not self.trace_no_resolve_check.isChecked(),
            cancel_event=self.trace_cancel_event,
            on_progress=self.trace_output.appendPlainText,
            on_result=lambda result, mode=mode: self._finish_trace(mode, result),
            on_finished=lambda: self._set_trace_running(False),
            error_title=f"{mode} 실행 실패",
        )

    def _finish_trace(self, mode: str, result: OperationResult) -> None:
        self.trace_status_label.setText(f"{mode}: {result.message}")
        if result.details and not self.trace_output.toPlainText().strip():
            self.trace_output.setPlainText(result.details)

    def _set_trace_running(self, running: bool) -> None:
        self.tracert_button.setEnabled(not running)
        self.pathping_button.setEnabled(not running)
        self.trace_cancel_button.setEnabled(running)

    def cancel_trace(self) -> None:
        if self.trace_cancel_event:
            self.trace_cancel_event.set()

    def load_interface_snapshot(self) -> None:
        self.tools_output.setPlainText("현재 인터페이스 정보를 불러오는 중...")
        self._start_worker(
            self.state.network_interface_service.list_adapters,
            on_result=lambda adapters: self.tools_output.setPlainText(
                self.state.network_interface_service.format_adapter_snapshot(adapters)
            ),
            error_title="인터페이스 정보 조회 실패",
        )

    def _run_tools_command(self, fn: Callable) -> None:
        self.tools_output.setPlainText("명령 실행 중...")
        self._start_worker(
            fn,
            on_result=lambda result: self.tools_output.setPlainText(result.details or result.message),
            error_title="도구 실행 실패",
        )

    def _update_iperf_mode_state(self) -> None:
        is_client = self.iperf_mode_combo.currentData() == "client"
        self.iperf_server_edit.setEnabled(is_client)
        self.iperf_streams_edit.setEnabled(is_client)
        self.iperf_duration_edit.setEnabled(is_client)
        self.iperf_reverse_check.setEnabled(is_client)
        self.iperf_server_edit.setPlaceholderText(
            "예: 192.168.0.10" if is_client else "서버 모드에서는 사용하지 않습니다."
        )

    def run_iperf_test(self) -> None:
        mode = str(self.iperf_mode_combo.currentData())
        try:
            port = self._positive_int_or_default(self.iperf_port_edit, "iperf 포트", 5201, minimum=1, maximum=65535)
            streams = (
                self._positive_int_or_default(self.iperf_streams_edit, "스트림 수", 1)
                if mode == "client"
                else 1
            )
            duration = (
                self._positive_int_or_default(self.iperf_duration_edit, "지속 시간", 10)
                if mode == "client"
                else 0
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return

        server = self.iperf_server_edit.text().strip()
        if mode == "client" and not server:
            QMessageBox.warning(self, "입력 확인", "클라이언트 모드에서는 서버 주소를 입력해 주세요.")
            return

        self.iperf_output.clear()
        self.iperf_cancel_event = Event()
        self._set_iperf_running(True)

        self._start_worker(
            self.state.iperf_service.run_test,
            mode,
            server,
            port,
            streams,
            duration,
            self.iperf_reverse_check.isChecked(),
            cancel_event=self.iperf_cancel_event,
            on_progress=self.iperf_output.appendPlainText,
            on_result=self._finish_iperf,
            on_finished=lambda: self._set_iperf_running(False),
            error_title="iperf3 실행 실패",
        )

    def _finish_iperf(self, result: OperationResult) -> None:
        if self.iperf_output.toPlainText().strip():
            self.iperf_output.appendPlainText("")
            self.iperf_output.appendPlainText(f"[결과] {result.message}")
            if result.details and not result.success:
                self.iperf_output.appendPlainText(result.details)
        else:
            self.iperf_output.setPlainText(result.message + ("\n\n" + result.details if result.details else ""))

    def _set_iperf_running(self, running: bool) -> None:
        self.iperf_run_button.setEnabled(not running)
        self.iperf_cancel_button.setEnabled(running)

    def cancel_iperf_test(self) -> None:
        if self.iperf_cancel_event:
            self.iperf_cancel_event.set()

    def export_selected_ping_logs(self) -> None:
        rows = self._selected_rows(self.ping_table)
        if not rows:
            QMessageBox.warning(self, "선택 필요", "로그를 저장할 Ping 항목을 먼저 선택해 주세요.")
            return

        folder = self._make_export_dir("ping_logs")
        for row in rows:
            name = self._cell(self.ping_table, row, 0)
            target = self._cell(self.ping_table, row, 1)
            lines = self.ping_log_lines.get((name, target), [])
            (folder / f"{self._safe(name)}_{self._safe(target)}.log").write_text(
                "\n".join(lines) + ("\n" if lines else ""),
                encoding="utf-8",
            )
        QMessageBox.information(self, "로그 저장 완료", f"{len(rows)}개 로그 파일을 저장했습니다.\n{folder}")

    def export_selected_tcp_logs(self) -> None:
        rows = self._selected_rows(self.tcp_table)
        if not rows:
            QMessageBox.warning(self, "선택 필요", "로그를 저장할 TCPing 항목을 먼저 선택해 주세요.")
            return

        folder = self._make_export_dir("tcp_logs")
        for row in rows:
            name = self._cell(self.tcp_table, row, 0)
            target = self._cell(self.tcp_table, row, 1)
            port = self._cell(self.tcp_table, row, 2)
            try:
                key = (name, target, int(port))
            except ValueError:
                continue
            lines = self.tcp_log_lines.get(key, [])
            (folder / f"{self._safe(name)}_{self._safe(target)}_{port}.log").write_text(
                "\n".join(lines) + ("\n" if lines else ""),
                encoding="utf-8",
            )
        QMessageBox.information(self, "로그 저장 완료", f"{len(rows)}개 로그 파일을 저장했습니다.\n{folder}")

    def _export_table_to_csv(self, table: QTableWidget, prefix: str) -> None:
        if table.rowCount() == 0:
            QMessageBox.warning(self, "내보내기 불가", "저장할 결과가 없습니다.")
            return

        path = timestamped_export_path(self.state.paths.exports_dir, prefix, "csv")
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([table.horizontalHeaderItem(column).text() for column in range(table.columnCount())])
            for row in range(table.rowCount()):
                writer.writerow([self._cell(table, row, column) for column in range(table.columnCount())])
        QMessageBox.information(self, "CSV 저장 완료", f"결과를 저장했습니다.\n{path}")

    def _make_export_dir(self, prefix: str):
        folder = self.state.paths.exports_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _selected_rows(self, table: QTableWidget) -> list[int]:
        return sorted({index.row() for index in table.selectionModel().selectedRows()})

    def _cell(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text() if item else ""

    def _safe(self, value: str) -> str:
        return re.sub(r'[\\/:*?"<>|]+', "_", value.strip()) or "item"

    def save_ui_state(self) -> dict:
        return {
            "current_tab": self.tab_widget.currentIndex(),
            "ping": {
                "targets": self.ping_targets_edit.toPlainText(),
                "count": self.ping_count_edit.text().strip(),
                "timeout_ms": self.ping_timeout_edit.text().strip(),
                "workers": self.ping_workers_edit.text().strip(),
                "continuous": self.ping_continuous_check.isChecked(),
            },
            "tcp": {
                "targets": self.tcp_targets_edit.toPlainText(),
                "ports": self.tcp_ports_edit.text().strip(),
                "count": self.tcp_count_edit.text().strip(),
                "timeout_ms": self.tcp_timeout_edit.text().strip(),
                "workers": self.tcp_workers_edit.text().strip(),
                "continuous": self.tcp_continuous_check.isChecked(),
            },
            "dns": {
                "query": self.dns_query_edit.text().strip(),
                "record_type": self.dns_type_combo.currentData()[0],
                "server": self.dns_server_edit.text().strip(),
            },
            "trace": {
                "target": self.trace_target_edit.text().strip(),
                "no_resolve": self.trace_no_resolve_check.isChecked(),
            },
            "iperf": {
                "mode": str(self.iperf_mode_combo.currentData() or ""),
                "server": self.iperf_server_edit.text().strip(),
                "port": self.iperf_port_edit.text().strip(),
                "streams": self.iperf_streams_edit.text().strip(),
                "duration": self.iperf_duration_edit.text().strip(),
                "reverse": self.iperf_reverse_check.isChecked(),
            },
        }

    def restore_ui_state(self, ui_state: dict | None) -> None:
        state = dict(ui_state or {})
        if not state:
            return

        current_tab = int(state.get("current_tab", 0) or 0)
        if 0 <= current_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(current_tab)

        ping_state = state.get("ping", {})
        self.ping_targets_edit.setPlainText(str(ping_state.get("targets", "") or ""))
        self.ping_count_edit.setText(str(ping_state.get("count", self.ping_count_edit.text()) or ""))
        self.ping_timeout_edit.setText(str(ping_state.get("timeout_ms", self.ping_timeout_edit.text()) or ""))
        self.ping_workers_edit.setText(str(ping_state.get("workers", self.ping_workers_edit.text()) or ""))
        self.ping_continuous_check.setChecked(bool(ping_state.get("continuous", False)))

        tcp_state = state.get("tcp", {})
        self.tcp_targets_edit.setPlainText(str(tcp_state.get("targets", "") or ""))
        self.tcp_ports_edit.setText(str(tcp_state.get("ports", self.tcp_ports_edit.text()) or ""))
        self.tcp_count_edit.setText(str(tcp_state.get("count", self.tcp_count_edit.text()) or ""))
        self.tcp_timeout_edit.setText(str(tcp_state.get("timeout_ms", self.tcp_timeout_edit.text()) or ""))
        self.tcp_workers_edit.setText(str(tcp_state.get("workers", self.tcp_workers_edit.text()) or ""))
        self.tcp_continuous_check.setChecked(bool(tcp_state.get("continuous", False)))

        dns_state = state.get("dns", {})
        self.dns_query_edit.setText(str(dns_state.get("query", "") or ""))
        self.dns_server_edit.setText(str(dns_state.get("server", "") or ""))
        dns_type = str(dns_state.get("record_type", "") or "")
        if dns_type:
            for index in range(self.dns_type_combo.count()):
                value, _description = self.dns_type_combo.itemData(index)
                if value == dns_type:
                    self.dns_type_combo.setCurrentIndex(index)
                    break
        self._update_dns_type_hint()

        trace_state = state.get("trace", {})
        self.trace_target_edit.setText(str(trace_state.get("target", "") or ""))
        self.trace_no_resolve_check.setChecked(bool(trace_state.get("no_resolve", False)))

        iperf_state = state.get("iperf", {})
        iperf_mode = str(iperf_state.get("mode", "") or "")
        if iperf_mode:
            index = self.iperf_mode_combo.findData(iperf_mode)
            if index >= 0:
                self.iperf_mode_combo.setCurrentIndex(index)
        self.iperf_server_edit.setText(str(iperf_state.get("server", "") or ""))
        self.iperf_port_edit.setText(str(iperf_state.get("port", self.iperf_port_edit.text()) or ""))
        self.iperf_streams_edit.setText(str(iperf_state.get("streams", self.iperf_streams_edit.text()) or ""))
        self.iperf_duration_edit.setText(str(iperf_state.get("duration", self.iperf_duration_edit.text()) or ""))
        self.iperf_reverse_check.setChecked(bool(iperf_state.get("reverse", False)))
        self._update_iperf_mode_state()

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
