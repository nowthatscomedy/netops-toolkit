from __future__ import annotations

import csv
from collections import Counter
import re
from datetime import datetime
from threading import Event
from typing import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from app.app_state import AppState
from app.models.network_models import ArpScanEntry, PublicIperfServer, TraceHop
from app.models.result_models import OperationResult, PingResult, TcpCheckResult
from app.utils.file_utils import timestamped_export_path
from app.utils.parser import parse_trace_hop_line, parse_trace_hops
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
        self.arp_cancel_event: Event | None = None
        self.iperf_cancel_event: Event | None = None
        self.iperf_manage_cancel_event: Event | None = None

        self.ping_row_map: dict[tuple[str, str], int] = {}
        self.tcp_row_map: dict[tuple[str, str, int], int] = {}
        self.trace_row_map: dict[int, int] = {}
        self.arp_subnet_candidates: list[str] = []
        self.ping_log_lines: dict[tuple[str, str], list[str]] = {}
        self.tcp_log_lines: dict[tuple[str, str, int], list[str]] = {}
        self._iperf_available = False
        self._iperf_manage_available = False
        self._iperf_manage_enabled = False
        self._public_iperf_refresh_in_progress = False
        self._preferred_public_iperf_key = ""
        self._preferred_public_iperf_region = ""
        self.public_iperf_all_servers: list[PublicIperfServer] = []
        self.public_iperf_servers: list[PublicIperfServer] = []
        self._public_iperf_fetched_at = ""
        self._public_iperf_from_cache = False
        self._public_iperf_stale = True

        self.fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._build_ui()
        self.refresh_arp_subnets()

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
        self.trace_table = QTableWidget(0, 7)
        self.trace_table.setHorizontalHeaderLabels(["Hop", "RTT1", "RTT2", "RTT3", "평균(ms)", "목적지", "상태"])
        self._setup_table(self.trace_table)
        self.trace_table.setMaximumHeight(220)
        layout.addWidget(self.trace_table)
        self.trace_output = self._output()
        layout.addWidget(self.trace_output, 1)

        self.tracert_button.clicked.connect(lambda: self.start_trace("tracert"))
        self.pathping_button.clicked.connect(lambda: self.start_trace("pathping"))
        self.trace_cancel_button.clicked.connect(self.cancel_trace)
        return page

    def _build_tools_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.tools_inner_tab = QTabWidget()
        self.tools_inner_tab.addTab(self._build_command_tools_page(), "명령 출력")
        self.tools_inner_tab.addTab(self._build_arp_scan_page(), "ARP 스캔")
        self.tools_inner_tab.addTab(self._build_oui_lookup_page(), "MAC OUI")
        layout.addWidget(self.tools_inner_tab, 1)

        self._refresh_oui_status_labels()
        return page

    def _build_command_tools_page(self) -> QWidget:
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

    def _build_arp_scan_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("ARP 스캔 / 같은 대역 장비 탐색")
        form = QFormLayout(group)
        self.arp_subnet_edit = QLineEdit()
        self.arp_subnet_edit.setPlaceholderText("예: 192.168.0.0/24")
        self.arp_subnet_combo = QComboBox()
        self.arp_subnet_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.arp_refresh_subnets_button = QPushButton("인터페이스 기준 불러오기")
        self.arp_use_selected_subnet_button = QPushButton("선택값 입력")
        self.arp_timeout_edit = QLineEdit()
        self.arp_timeout_edit.setPlaceholderText("800")
        self.arp_workers_edit = QLineEdit()
        self.arp_workers_edit.setPlaceholderText("64")
        self.arp_start_button = QPushButton("스캔")
        self.arp_cancel_button = QPushButton("중지")
        self.arp_cancel_button.setEnabled(False)
        self.arp_refresh_oui_button = QPushButton("OUI 캐시 갱신")
        self.arp_oui_status_label = QLabel()
        self.arp_oui_status_label.setStyleSheet("color:#666;")

        subnet_button_row = QHBoxLayout()
        subnet_button_row.addWidget(self.arp_subnet_combo, 1)
        subnet_button_row.addWidget(self.arp_refresh_subnets_button)
        subnet_button_row.addWidget(self.arp_use_selected_subnet_button)

        action_row = QHBoxLayout()
        action_row.addWidget(self.arp_start_button)
        action_row.addWidget(self.arp_cancel_button)
        action_row.addSpacing(8)
        action_row.addWidget(self.arp_refresh_oui_button)
        action_row.addStretch(1)

        form.addRow("서브넷", self.arp_subnet_edit)
        form.addRow("활성 서브넷", subnet_button_row)
        form.addRow("Timeout (ms)", self.arp_timeout_edit)
        form.addRow("동시 실행 수", self.arp_workers_edit)
        form.addRow("", action_row)
        form.addRow("OUI 캐시", self.arp_oui_status_label)
        layout.addWidget(group)

        self.arp_table = QTableWidget(0, 7)
        self.arp_table.setHorizontalHeaderLabels(["IP", "MAC", "벤더", "상태", "응답(ms)", "ARP 타입", "인터페이스"])
        self._setup_table(self.arp_table)
        layout.addWidget(self.arp_table, 1)

        self.arp_output = self._output()
        self.arp_output.setMaximumHeight(150)
        layout.addWidget(self.arp_output)

        self.arp_refresh_subnets_button.clicked.connect(self.refresh_arp_subnets)
        self.arp_use_selected_subnet_button.clicked.connect(self.use_selected_arp_subnet)
        self.arp_start_button.clicked.connect(self.start_arp_scan)
        self.arp_cancel_button.clicked.connect(self.cancel_arp_scan)
        self.arp_refresh_oui_button.clicked.connect(lambda: self.refresh_oui_cache(self.arp_output))
        return page

    def _build_oui_lookup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("MAC OUI 벤더 조회")
        form = QFormLayout(group)
        self.oui_mac_edit = QLineEdit()
        self.oui_mac_edit.setPlaceholderText("예: 58:86:94:A1:5A:BA")
        self.oui_lookup_button = QPushButton("조회")
        self.oui_refresh_button = QPushButton("IEEE 캐시 갱신")
        self.oui_status_label = QLabel()
        self.oui_status_label.setStyleSheet("color:#666;")

        action_row = QHBoxLayout()
        action_row.addWidget(self.oui_lookup_button)
        action_row.addWidget(self.oui_refresh_button)
        action_row.addStretch(1)

        form.addRow("MAC 주소", self.oui_mac_edit)
        form.addRow("", action_row)
        form.addRow("캐시 상태", self.oui_status_label)
        layout.addWidget(group)

        self.oui_result_output = self._output()
        layout.addWidget(self.oui_result_output, 1)

        self.oui_lookup_button.clicked.connect(self.lookup_oui_vendor)
        self.oui_refresh_button.clicked.connect(lambda: self.refresh_oui_cache(self.oui_result_output))
        return page

    def _build_iperf_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("iperf3")
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 8, 8, 8)
        group_layout.setSpacing(4)

        self.iperf_mode_combo = QComboBox()
        self.iperf_mode_combo.addItem("클라이언트", "client")
        self.iperf_mode_combo.addItem("서버", "server")
        self.iperf_use_public_server_check = QCheckBox("공개 서버 사용")
        self.iperf_public_refresh_button = QPushButton("목록 갱신")
        self.iperf_public_region_combo = QComboBox()
        self.iperf_public_region_combo.addItem("전체 지역", "")
        self.iperf_public_region_combo.setMinimumWidth(130)
        self.iperf_public_server_combo = QComboBox()
        self.iperf_public_server_combo.addItem("공개 서버 목록 확인 중...", "")
        self.iperf_public_info_label = QLabel("목록 상태 확인 중")
        self.iperf_public_info_label.setStyleSheet("color:#666;")
        self.iperf_server_edit = QLineEdit()
        self.iperf_server_edit.setPlaceholderText("예: 192.168.0.10")
        self.iperf_port_edit = QLineEdit()
        self.iperf_port_edit.setPlaceholderText("5201")
        self.iperf_port_edit.setMaximumWidth(90)
        self.iperf_streams_edit = QLineEdit()
        self.iperf_streams_edit.setPlaceholderText("1")
        self.iperf_streams_edit.setMaximumWidth(90)
        self.iperf_duration_edit = QLineEdit()
        self.iperf_duration_edit.setPlaceholderText("10")
        self.iperf_duration_edit.setMaximumWidth(90)
        self.iperf_reverse_check = QCheckBox("Reverse (-R)")
        self.iperf_udp_check = QCheckBox("UDP (-u)")
        self.iperf_ipv6_check = QCheckBox("IPv6 (-6)")

        self.iperf_run_button = QPushButton("실행")
        self.iperf_cancel_button = QPushButton("중지")
        self.iperf_cancel_button.setEnabled(False)

        self.iperf_status_label = QLabel()
        self.iperf_status_label.setWordWrap(False)
        self.iperf_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.iperf_refresh_button = QPushButton("상태 새로고침")
        self.iperf_manage_button = QPushButton("winget 설치")
        self.iperf_download_button = QPushButton("패키지 페이지")

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("모드"))
        mode_row.addWidget(self.iperf_mode_combo)
        mode_row.addSpacing(10)
        mode_row.addWidget(self.iperf_use_public_server_check)
        mode_row.addWidget(self.iperf_public_refresh_button)
        mode_row.addStretch(1)
        group_layout.addLayout(mode_row)

        public_row = QHBoxLayout()
        public_row.addWidget(QLabel("지역"))
        public_row.addWidget(self.iperf_public_region_combo)
        public_row.addSpacing(6)
        public_row.addWidget(QLabel("공개 서버"))
        public_row.addWidget(self.iperf_public_server_combo, 1)
        self.iperf_public_row_widget = QWidget()
        self.iperf_public_row_widget.setLayout(public_row)
        group_layout.addWidget(self.iperf_public_row_widget)

        public_info_row = QHBoxLayout()
        public_info_row.addWidget(self.iperf_public_info_label, 1)
        self.iperf_public_info_row_widget = QWidget()
        self.iperf_public_info_row_widget.setLayout(public_info_row)
        group_layout.addWidget(self.iperf_public_info_row_widget)

        params_row = QHBoxLayout()
        params_row.addWidget(QLabel("서버"))
        params_row.addWidget(self.iperf_server_edit, 1)
        params_row.addSpacing(6)
        params_row.addWidget(QLabel("포트"))
        params_row.addWidget(self.iperf_port_edit)
        params_row.addSpacing(6)
        params_row.addWidget(QLabel("스트림"))
        params_row.addWidget(self.iperf_streams_edit)
        params_row.addSpacing(6)
        params_row.addWidget(QLabel("지속(초)"))
        params_row.addWidget(self.iperf_duration_edit)
        params_row.addSpacing(6)
        params_row.addWidget(self.iperf_reverse_check)
        params_row.addWidget(self.iperf_udp_check)
        params_row.addWidget(self.iperf_ipv6_check)
        group_layout.addLayout(params_row)

        action_row = QHBoxLayout()
        action_row.addWidget(self.iperf_run_button)
        action_row.addWidget(self.iperf_cancel_button)
        action_row.addSpacing(8)
        action_row.addWidget(self.iperf_refresh_button)
        action_row.addWidget(self.iperf_manage_button)
        action_row.addWidget(self.iperf_download_button)
        action_row.addSpacing(8)
        action_row.addWidget(self.iperf_status_label, 1)
        action_row.addStretch(1)
        group_layout.addLayout(action_row)

        layout.addWidget(group, 0)

        self.iperf_output = self._output()
        layout.addWidget(self.iperf_output, 1)

        self.iperf_mode_combo.currentIndexChanged.connect(self._update_iperf_mode_state)
        self.iperf_use_public_server_check.toggled.connect(self._toggle_public_iperf_mode)
        self.iperf_public_region_combo.currentIndexChanged.connect(self._handle_public_iperf_region_changed)
        self.iperf_public_server_combo.currentIndexChanged.connect(self._handle_public_iperf_selection_changed)
        self.iperf_public_refresh_button.clicked.connect(lambda: self.refresh_public_iperf_servers(force_refresh=True))
        self.iperf_run_button.clicked.connect(self.run_iperf_test)
        self.iperf_cancel_button.clicked.connect(self.cancel_iperf_test)
        self.iperf_refresh_button.clicked.connect(self.refresh_iperf_availability)
        self.iperf_manage_button.clicked.connect(self.manage_iperf_install)
        self.iperf_download_button.clicked.connect(self.open_iperf_download_page)
        self._update_iperf_mode_state()
        self.refresh_iperf_availability()
        self._load_cached_public_iperf_servers()
        self.refresh_public_iperf_servers(force_refresh=False)
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
        self.trace_table.setRowCount(0)
        self.trace_row_map.clear()
        self.trace_status_label.setText(f"{mode} 실행 중...")
        self.trace_cancel_event = Event()
        self._set_trace_running(True)

        runner = self.state.trace_service.run_tracert if mode == "tracert" else self.state.trace_service.run_pathping
        self._start_worker(
            runner,
            target,
            not self.trace_no_resolve_check.isChecked(),
            cancel_event=self.trace_cancel_event,
            on_progress=self._handle_trace_progress,
            on_result=lambda result, mode=mode: self._finish_trace(mode, result),
            on_finished=lambda: self._set_trace_running(False),
            error_title=f"{mode} 실행 실패",
        )

    def _handle_trace_progress(self, line: str) -> None:
        self.trace_output.appendPlainText(line)
        hop = parse_trace_hop_line(line)
        if hop is not None:
            self._upsert_trace_hop(hop)

    def _finish_trace(self, mode: str, result: OperationResult) -> None:
        self.trace_status_label.setText(f"{mode}: {result.message}")
        if result.details and not self.trace_output.toPlainText().strip():
            self.trace_output.setPlainText(result.details)
        for hop in parse_trace_hops(result.details or self.trace_output.toPlainText()):
            self._upsert_trace_hop(hop)

    def _set_trace_running(self, running: bool) -> None:
        self.tracert_button.setEnabled(not running)
        self.pathping_button.setEnabled(not running)
        self.trace_cancel_button.setEnabled(running)

    def cancel_trace(self) -> None:
        if self.trace_cancel_event:
            self.trace_cancel_event.set()

    def _upsert_trace_hop(self, hop: TraceHop) -> None:
        row = self.trace_row_map.get(hop.hop_number)
        if row is None:
            row = self.trace_table.rowCount()
            self.trace_table.insertRow(row)
            self.trace_row_map[hop.hop_number] = row

        values = [
            str(hop.hop_number),
            hop.probe_1 or "-",
            hop.probe_2 or "-",
            hop.probe_3 or "-",
            f"{hop.average_ms:.2f}" if hop.average_ms is not None else "-",
            hop.endpoint_text,
            hop.status or "-",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 6:
                if hop.status == "정상":
                    item.setForeground(QColor("#1b5e20"))
                elif hop.status == "시간 초과":
                    item.setForeground(QColor("#b71c1c"))
                else:
                    item.setForeground(QColor("#ef6c00"))
            self.trace_table.setItem(row, column, item)

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

    def refresh_arp_subnets(self) -> None:
        self.arp_output.setPlainText("활성 IPv4 서브넷을 확인하는 중...")
        self._start_worker(
            self.state.network_interface_service.list_adapters,
            on_result=self._populate_arp_subnets,
            error_title="활성 서브넷 조회 실패",
        )

    def _populate_arp_subnets(self, adapters) -> None:
        current_subnet = str(self.arp_subnet_combo.currentData() or "")
        candidates = self.state.arp_scan_service.list_candidate_subnets(adapters)
        self.arp_subnet_combo.clear()
        self.arp_subnet_candidates = [subnet for _label, subnet in candidates]
        for label, subnet in candidates:
            self.arp_subnet_combo.addItem(label, subnet)

        if current_subnet:
            index = self.arp_subnet_combo.findData(current_subnet)
            if index >= 0:
                self.arp_subnet_combo.setCurrentIndex(index)

        if candidates:
            self.arp_output.setPlainText(f"활성 서브넷 {len(candidates)}개를 찾았습니다.")
        else:
            self.arp_output.setPlainText("사용 가능한 활성 IPv4 서브넷을 찾지 못했습니다.")

    def use_selected_arp_subnet(self) -> None:
        subnet = str(self.arp_subnet_combo.currentData() or "").strip()
        if not subnet:
            QMessageBox.warning(self, "선택 필요", "먼저 활성 서브넷 목록을 불러와 선택해 주세요.")
            return
        self.arp_subnet_edit.setText(subnet)

    def start_arp_scan(self) -> None:
        try:
            timeout_ms = self._positive_int_or_default(self.arp_timeout_edit, "ARP Timeout", 800)
            workers = self._positive_int_or_default(self.arp_workers_edit, "ARP 동시 실행 수", 64)
        except ValidationError as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return

        self.arp_table.setRowCount(0)
        self.arp_output.clear()
        self.arp_cancel_event = Event()
        self._set_arp_running(True)
        self._start_worker(
            self.state.arp_scan_service.run_scan,
            self.arp_subnet_edit.text().strip(),
            timeout_ms,
            workers,
            cancel_event=self.arp_cancel_event,
            on_progress=self.arp_output.appendPlainText,
            on_result=self._finish_arp_scan,
            on_finished=lambda: self._set_arp_running(False),
            error_title="ARP 스캔 실패",
        )

    def _finish_arp_scan(self, result: OperationResult) -> None:
        entries = result.payload if isinstance(result.payload, list) else []
        self._populate_arp_table(entries)
        if self.arp_output.toPlainText().strip():
            self.arp_output.appendPlainText("")
            self.arp_output.appendPlainText(f"[결과] {result.message}")
        else:
            self.arp_output.setPlainText(result.message)

    def _populate_arp_table(self, entries: list[ArpScanEntry]) -> None:
        self.arp_table.setRowCount(0)
        for entry in entries:
            row = self.arp_table.rowCount()
            self.arp_table.insertRow(row)
            values = [
                entry.ip_address,
                entry.mac_address or "-",
                entry.vendor or "-",
                entry.status_text,
                f"{entry.response_ms:.0f}" if entry.response_ms is not None else "-",
                entry.arp_type or "-",
                entry.interface_name or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    if entry.reachable:
                        item.setForeground(QColor("#1b5e20"))
                    elif entry.mac_address:
                        item.setForeground(QColor("#ef6c00"))
                    else:
                        item.setForeground(QColor("#b71c1c"))
                self.arp_table.setItem(row, column, item)

    def _set_arp_running(self, running: bool) -> None:
        self.arp_start_button.setEnabled(not running)
        self.arp_cancel_button.setEnabled(running)
        self.arp_refresh_subnets_button.setEnabled(not running)
        self.arp_use_selected_subnet_button.setEnabled(not running)
        self.arp_refresh_oui_button.setEnabled(not running)

    def cancel_arp_scan(self) -> None:
        if self.arp_cancel_event:
            self.arp_cancel_event.set()

    def lookup_oui_vendor(self) -> None:
        mac_address = self.oui_mac_edit.text().strip()
        if not mac_address:
            QMessageBox.warning(self, "입력 확인", "조회할 MAC 주소를 입력해 주세요.")
            return

        match = self.state.oui_service.lookup(mac_address)
        normalized = self.state.oui_service.normalize_mac(mac_address)
        if match is None:
            self.oui_result_output.setPlainText(
                "\n".join(
                    [
                        f"입력 MAC: {mac_address}",
                        f"정규화: {normalized or '-'}",
                        "",
                        "일치하는 OUI를 찾지 못했습니다.",
                        self.state.oui_service.cache_summary(),
                    ]
                )
            )
            return

        self.oui_result_output.setPlainText(
            "\n".join(
                [
                    f"입력 MAC: {mac_address}",
                    f"정규화: {normalized}",
                    f"벤더: {match.organization}",
                    f"레지스트리: {match.registry}",
                    f"접두어: {match.prefix} ({match.prefix_bits} bit)",
                    "",
                    self.state.oui_service.cache_summary(),
                ]
            )
        )

    def refresh_oui_cache(self, output_widget: QPlainTextEdit) -> None:
        output_widget.clear()
        self._start_worker(
            self.state.oui_service.refresh_cache,
            on_progress=output_widget.appendPlainText,
            on_result=lambda result, widget=output_widget: self._finish_oui_refresh(result, widget),
            error_title="OUI 캐시 갱신 실패",
        )

    def _finish_oui_refresh(self, result: OperationResult, output_widget: QPlainTextEdit) -> None:
        self._refresh_oui_status_labels()
        if output_widget.toPlainText().strip():
            output_widget.appendPlainText("")
            output_widget.appendPlainText(f"[결과] {result.message}")
            if result.details:
                output_widget.appendPlainText(result.details)
        else:
            output_widget.setPlainText(result.message + ("\n\n" + result.details if result.details else ""))

    def _refresh_oui_status_labels(self) -> None:
        summary = self.state.oui_service.cache_summary()
        if hasattr(self, "arp_oui_status_label"):
            self.arp_oui_status_label.setText(summary)
        if hasattr(self, "oui_status_label"):
            self.oui_status_label.setText(summary)

    def _load_cached_public_iperf_servers(self) -> None:
        cached = self.state.public_iperf_service.load_cached_servers()
        payload = cached.payload if isinstance(cached.payload, dict) else {}
        servers = payload.get("servers", [])
        if isinstance(servers, list) and servers:
            self._apply_public_iperf_servers(
                servers,
                fetched_at=str(payload.get("fetched_at", "") or ""),
                from_cache=True,
                stale=bool(payload.get("stale", False)),
            )
        else:
            self._set_public_iperf_info("공개 iperf 서버 캐시가 없습니다. 인터넷 연결 시 자동으로 목록을 가져옵니다.")

    def refresh_public_iperf_servers(self, force_refresh: bool = False) -> None:
        if self._public_iperf_refresh_in_progress:
            return
        self._public_iperf_refresh_in_progress = True
        self._set_public_iperf_info("공개 iperf 서버 목록을 갱신하는 중입니다...")
        self._update_iperf_mode_state()
        self._start_worker(
            self.state.public_iperf_service.fetch_public_servers,
            force_refresh=force_refresh,
            on_result=self._finish_public_iperf_refresh,
            on_finished=self._finish_public_iperf_refresh_state,
            error_title="공개 iperf 서버 목록 갱신 실패",
        )

    def _finish_public_iperf_refresh(self, result: OperationResult) -> None:
        payload = result.payload if isinstance(result.payload, dict) else {}
        servers = payload.get("servers", [])
        if isinstance(servers, list) and servers:
            self._apply_public_iperf_servers(
                servers,
                fetched_at=str(payload.get("fetched_at", "") or ""),
                from_cache=bool(payload.get("from_cache", False)),
                stale=bool(payload.get("stale", False)),
            )
        elif result.success:
            self._set_public_iperf_info(result.message)
        else:
            self._set_public_iperf_info(result.message)
            self.iperf_output.setPlainText(result.details or result.message)

    def _finish_public_iperf_refresh_state(self) -> None:
        self._public_iperf_refresh_in_progress = False
        self._update_iperf_mode_state()

    def _region_label(self, region: str) -> str:
        normalized = (region or "").strip()
        mapping = {
            "asia": "아시아",
            "europe": "유럽",
            "north america": "북미",
            "south america": "남미",
            "oceania": "오세아니아",
            "africa": "아프리카",
            "middle east": "중동",
        }
        return mapping.get(normalized.lower(), normalized or "기타")

    def _server_sort_key(self, server: PublicIperfServer) -> tuple[str, str, str]:
        region = (server.region or "ZZZ").lower()
        site = (server.site or server.name or server.host).lower()
        return (region, site, server.host.lower())

    def _public_server_item_text(self, server: PublicIperfServer, include_region: bool) -> str:
        location = server.site or server.name or server.host
        country = f" ({server.country_code})" if server.country_code and server.country_code not in location else ""
        parts: list[str] = []
        if include_region and server.region:
            parts.append(f"[{self._region_label(server.region)}]")
        parts.append(f"{location}{country}")
        parts.append(f"{server.host}:{server.port_spec}")
        if server.speed:
            parts.append(f"{server.speed} Gb/s")
        if server.options:
            parts.append(server.options)
        return " | ".join(parts)

    def _refresh_public_region_combo(self) -> None:
        previous_region = self._preferred_public_iperf_region or str(self.iperf_public_region_combo.currentData() or "")
        counts = Counter((server.region or "").strip() for server in self.public_iperf_all_servers if (server.region or "").strip())
        self.iperf_public_region_combo.blockSignals(True)
        self.iperf_public_region_combo.clear()
        total_count = len(self.public_iperf_all_servers)
        self.iperf_public_region_combo.addItem(f"전체 지역 ({total_count})", "")
        for region in sorted(counts, key=lambda item: self._region_label(item).lower()):
            self.iperf_public_region_combo.addItem(f"{self._region_label(region)} ({counts[region]})", region)
        index = self.iperf_public_region_combo.findData(previous_region)
        self.iperf_public_region_combo.setCurrentIndex(index if index >= 0 else 0)
        self.iperf_public_region_combo.blockSignals(False)
        self._preferred_public_iperf_region = str(self.iperf_public_region_combo.currentData() or "")

    def _rebuild_public_iperf_server_combo(self, previous_key: str = "") -> None:
        selected_region = str(self.iperf_public_region_combo.currentData() or "")
        self._preferred_public_iperf_region = selected_region
        if selected_region:
            self.public_iperf_servers = [
                server for server in self.public_iperf_all_servers if (server.region or "").strip() == selected_region
            ]
        else:
            self.public_iperf_servers = list(self.public_iperf_all_servers)

        include_region = not bool(selected_region)
        self.iperf_public_server_combo.blockSignals(True)
        self.iperf_public_server_combo.clear()
        for server in self.public_iperf_servers:
            self.iperf_public_server_combo.addItem(
                self._public_server_item_text(server, include_region=include_region),
                server.key,
            )
        self.iperf_public_server_combo.blockSignals(False)

        if previous_key:
            index = self.iperf_public_server_combo.findData(previous_key)
            if index >= 0:
                self.iperf_public_server_combo.setCurrentIndex(index)
                self._preferred_public_iperf_key = previous_key

        if self.iperf_public_server_combo.currentIndex() < 0 and self.iperf_public_server_combo.count() > 0:
            self.iperf_public_server_combo.setCurrentIndex(0)

    def _apply_public_iperf_servers(
        self,
        servers: list[PublicIperfServer],
        fetched_at: str = "",
        from_cache: bool = False,
        stale: bool = False,
    ) -> None:
        previous_key = self._preferred_public_iperf_key or str(self.iperf_public_server_combo.currentData() or "")
        self._public_iperf_fetched_at = fetched_at
        self._public_iperf_from_cache = from_cache
        self._public_iperf_stale = stale
        self.public_iperf_all_servers = sorted(list(servers), key=self._server_sort_key)
        self._refresh_public_region_combo()
        self._rebuild_public_iperf_server_combo(previous_key)
        selected = self._selected_public_iperf_server()
        if selected:
            self._preferred_public_iperf_key = selected.key
            self.iperf_public_server_combo.setToolTip(selected.summary_text or selected.display_name)
        else:
            self.iperf_public_server_combo.setToolTip("")

        self._refresh_public_iperf_info_message()
        self._sync_public_iperf_target(overwrite_port=False)
        self._update_iperf_mode_state()

    def _selected_public_iperf_server(self) -> PublicIperfServer | None:
        key = str(self.iperf_public_server_combo.currentData() or "")
        if not key:
            return None
        for server in self.public_iperf_servers:
            if server.key == key:
                return server
        return None

    def _handle_public_iperf_selection_changed(self) -> None:
        selected = self._selected_public_iperf_server()
        if selected:
            self._preferred_public_iperf_key = selected.key
            self.iperf_public_server_combo.setToolTip(selected.summary_text or selected.display_name)
        else:
            self.iperf_public_server_combo.setToolTip("")
        self._sync_public_iperf_target(overwrite_port=True)
        self._update_iperf_mode_state()

    def _handle_public_iperf_region_changed(self) -> None:
        previous_key = self._preferred_public_iperf_key
        self._rebuild_public_iperf_server_combo(previous_key)
        selected = self._selected_public_iperf_server()
        if selected:
            self._preferred_public_iperf_key = selected.key
            self.iperf_public_server_combo.setToolTip(selected.summary_text or selected.display_name)
        else:
            self.iperf_public_server_combo.setToolTip("")
        self._refresh_public_iperf_info_message()
        self._sync_public_iperf_target(overwrite_port=False)
        self._update_iperf_mode_state()

    def _toggle_public_iperf_mode(self, checked: bool) -> None:
        if checked:
            self._sync_public_iperf_target(overwrite_port=False)
        self._update_iperf_mode_state()

    def _sync_public_iperf_target(self, overwrite_port: bool) -> None:
        if self.iperf_mode_combo.currentData() != "client":
            return
        if not self.iperf_use_public_server_check.isChecked():
            return
        selected = self._selected_public_iperf_server()
        if not selected:
            return
        self.iperf_server_edit.setText(selected.host)
        current_port = self.iperf_port_edit.text().strip()
        if overwrite_port or not current_port:
            self.iperf_port_edit.setText(str(selected.default_port))

    def _set_public_iperf_info(self, text: str) -> None:
        compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
        self.iperf_public_info_label.setText(compact or "-")
        self.iperf_public_info_label.setToolTip(text)

    def _refresh_public_iperf_info_message(self) -> None:
        if not self.public_iperf_all_servers:
            return
        source_text = "캐시" if self._public_iperf_from_cache else "온라인"
        fetched_text = self._format_timestamp_text(self._public_iperf_fetched_at)
        total_count = len(self.public_iperf_all_servers)
        filtered_count = len(self.public_iperf_servers)
        region_text = ""
        if self._preferred_public_iperf_region:
            region_name = self._region_label(self._preferred_public_iperf_region)
            region_text = f" · {region_name} {filtered_count}/{total_count}개"
        message = f"{source_text} {total_count}개{region_text}"
        if fetched_text:
            message += f" · {fetched_text}"
        if self._public_iperf_stale:
            message += " · 오래된 캐시"
        self._set_public_iperf_info(message)

    def _format_timestamp_text(self, value: str) -> str:
        if not value:
            return ""
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return value
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")

    def _set_iperf_option_enabled(
        self,
        checkbox: QCheckBox,
        enabled: bool,
        unsupported_message: str = "",
    ) -> None:
        checkbox.setEnabled(enabled)
        checkbox.setToolTip("" if enabled else unsupported_message)
        if not enabled and checkbox.isChecked():
            checkbox.setChecked(False)

    def _update_iperf_option_state(self, is_client: bool, use_public_requested: bool) -> None:
        if not is_client:
            self._set_iperf_option_enabled(self.iperf_reverse_check, False)
            self._set_iperf_option_enabled(self.iperf_udp_check, False)
            self._set_iperf_option_enabled(self.iperf_ipv6_check, True)
            return

        if not use_public_requested:
            self._set_iperf_option_enabled(self.iperf_reverse_check, True)
            self._set_iperf_option_enabled(self.iperf_udp_check, True)
            self._set_iperf_option_enabled(self.iperf_ipv6_check, True)
            return

        selected = self._selected_public_iperf_server()
        if selected is None:
            unavailable_text = "공개 서버를 먼저 선택해 주세요."
            self._set_iperf_option_enabled(self.iperf_reverse_check, False, unavailable_text)
            self._set_iperf_option_enabled(self.iperf_udp_check, False, unavailable_text)
            self._set_iperf_option_enabled(self.iperf_ipv6_check, False, unavailable_text)
            return

        self._set_iperf_option_enabled(
            self.iperf_reverse_check,
            selected.supports_option("-R"),
            "선택한 공개 서버는 Reverse(-R)를 지원하지 않습니다.",
        )
        self._set_iperf_option_enabled(
            self.iperf_udp_check,
            selected.supports_option("-u"),
            "선택한 공개 서버는 UDP(-u)를 지원하지 않습니다.",
        )
        self._set_iperf_option_enabled(
            self.iperf_ipv6_check,
            selected.supports_option("-6"),
            "선택한 공개 서버는 IPv6(-6)를 지원하지 않습니다.",
        )

    def _update_iperf_mode_state(self) -> None:
        is_client = self.iperf_mode_combo.currentData() == "client"
        use_public = is_client and self.iperf_use_public_server_check.isChecked() and bool(self.public_iperf_servers)
        show_public_section = is_client and self.iperf_use_public_server_check.isChecked()
        self.iperf_use_public_server_check.setEnabled(is_client)
        self.iperf_public_region_combo.setEnabled(is_client and show_public_section and bool(self.public_iperf_all_servers))
        self.iperf_public_server_combo.setEnabled(is_client and use_public and bool(self.public_iperf_servers))
        self.iperf_public_refresh_button.setEnabled(is_client and not self._public_iperf_refresh_in_progress)
        self.iperf_public_row_widget.setVisible(show_public_section)
        self.iperf_public_info_row_widget.setVisible(show_public_section)
        self.iperf_server_edit.setEnabled(is_client and not use_public)
        self.iperf_streams_edit.setEnabled(is_client)
        self.iperf_duration_edit.setEnabled(is_client)
        self._update_iperf_option_state(is_client, show_public_section)
        self.iperf_server_edit.setPlaceholderText(
            "예: 192.168.0.10"
            if is_client and not use_public
            else "공개 서버 선택값이 자동으로 채워집니다."
            if is_client
            else "서버 모드에서는 사용하지 않습니다."
        )

    def refresh_iperf_availability(self) -> None:
        executable_path, source = self.state.iperf_service.executable_details()
        manage_state = self.state.iperf_service.managed_install_state()
        self._iperf_available = executable_path is not None
        self._iperf_manage_available = bool(manage_state["available"])
        self._iperf_manage_enabled = bool(manage_state["button_enabled"])
        self.iperf_manage_button.setText(str(manage_state["action_label"]))

        if self._iperf_available:
            version = self.state.iperf_service.executable_version(executable_path)
            if self._iperf_manage_available and self._iperf_manage_enabled:
                text = "업데이트 가능"
                if version:
                    text += f" (현재 {version})"
                self.iperf_status_label.setText(text)
                self.iperf_status_label.setToolTip(executable_path or "")
                self.iperf_status_label.setStyleSheet("color:#8d6e00;")
                self.iperf_status_label.show()
            else:
                self.iperf_status_label.clear()
                self.iperf_status_label.setToolTip(executable_path or "")
                self.iperf_status_label.hide()
        else:
            parts = ["iperf3 없음"]
            if self._iperf_manage_available:
                parts.append("winget 설치 가능")
                tooltip = (
                    "현재 iperf3를 찾지 못했습니다.\n"
                    f"1) '{manage_state['action_label']}' 버튼으로 현재 사용자에 설치/업데이트\n"
                    "2) 시스템 PATH에 iperf3를 설치한 뒤 '상태 새로고침' 실행"
                )
            else:
                parts.append("수동 설치 필요")
                tooltip = (
                    "현재 iperf3를 찾지 못했습니다.\n"
                    "시스템 PATH에 iperf3를 설치한 뒤 '상태 새로고침'을 실행해 주세요."
                )
            self.iperf_status_label.setText(" | ".join(parts))
            self.iperf_status_label.setToolTip(tooltip)
            self.iperf_status_label.setStyleSheet("color:#a33;")
            self.iperf_status_label.show()

        self._set_iperf_running(self.iperf_cancel_button.isEnabled())

    def open_iperf_download_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.state.iperf_service.managed_package_page()))

    def manage_iperf_install(self) -> None:
        manage_state = self.state.iperf_service.managed_install_state()
        if not bool(manage_state["available"]):
            QMessageBox.warning(
                self,
                "winget 사용 불가",
                "이 시스템에서는 winget을 찾지 못해 프로그램 내부 설치를 진행할 수 없습니다.",
            )
            return
        if not bool(manage_state["button_enabled"]):
            QMessageBox.information(
                self,
                "최신 버전 사용 중",
                "현재 winget 기준 최신 iperf3가 이미 설치되어 있습니다.",
            )
            return

        action_label = "업데이트" if bool(manage_state["installed"]) else "설치"
        reply = QMessageBox.question(
            self,
            "iperf3 관리형 설치",
            (
                f"iperf3를 winget 패키지로 {action_label}하시겠습니까?\n\n"
                f"패키지 ID: {manage_state['package_id']}\n"
                f"패키지 페이지: {manage_state['package_url']}\n\n"
                "현재 사용자 범위에 설치되며, 실행 파일이 준비되면 바로 앱에서 사용할 수 있습니다."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.iperf_output.clear()
        self.iperf_manage_cancel_event = Event()
        self._set_iperf_running(True)

        self._start_worker(
            self.state.iperf_service.install_or_update_managed,
            cancel_event=self.iperf_manage_cancel_event,
            on_progress=self.iperf_output.appendPlainText,
            on_result=self._finish_iperf_manage,
            on_finished=self._finish_iperf_operation,
            error_title="iperf3 설치 실패",
        )

    def run_iperf_test(self) -> None:
        self.refresh_iperf_availability()
        if not self._iperf_available:
            if self._iperf_manage_available:
                reply = QMessageBox.question(
                    self,
                    "iperf3 설치 필요",
                    (
                        "iperf3 실행 파일을 찾지 못했습니다.\n\n"
                        "지금 winget으로 설치/업데이트하시겠습니까?"
                    ),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self.manage_iperf_install()
                return

            QMessageBox.information(
                self,
                "iperf3 설치 필요",
                "iperf3 실행 파일을 찾지 못했습니다.\n\n"
                "프로그램 폴더에 iperf3.exe를 넣거나 시스템 PATH에 iperf3를 설치해 주세요.",
            )
            return

        mode = str(self.iperf_mode_combo.currentData())
        if mode == "client":
            self._sync_public_iperf_target(overwrite_port=False)
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
            if self.iperf_use_public_server_check.isChecked():
                QMessageBox.warning(self, "입력 확인", "공개 서버 목록을 먼저 불러오거나 직접 서버 주소를 입력해 주세요.")
            else:
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
            self.iperf_udp_check.isChecked(),
            self.iperf_ipv6_check.isChecked(),
            cancel_event=self.iperf_cancel_event,
            on_progress=self.iperf_output.appendPlainText,
            on_result=self._finish_iperf,
            on_finished=self._finish_iperf_operation,
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

    def _finish_iperf_manage(self, result: OperationResult) -> None:
        streamed = self.iperf_output.toPlainText().strip()
        summary = f"[결과] {result.message}"
        if result.details and (not streamed or result.success):
            summary = f"{summary}\n{result.details}"

        if streamed:
            self.iperf_output.appendPlainText("")
            self.iperf_output.appendPlainText(summary)
            return

        self.iperf_output.setPlainText(summary)

    def _finish_iperf_operation(self) -> None:
        self.iperf_cancel_event = None
        self.iperf_manage_cancel_event = None
        self._set_iperf_running(False)
        self.refresh_iperf_availability()

    def _set_iperf_running(self, running: bool) -> None:
        self.iperf_run_button.setEnabled((not running) and self._iperf_available)
        self.iperf_cancel_button.setEnabled(running)
        self.iperf_refresh_button.setEnabled(not running)
        self.iperf_manage_button.setVisible(self._iperf_manage_enabled)
        self.iperf_manage_button.setEnabled((not running) and self._iperf_manage_enabled)
        self.iperf_public_refresh_button.setEnabled(
            (not running)
            and (self.iperf_mode_combo.currentData() == "client")
            and (not self._public_iperf_refresh_in_progress)
        )

    def cancel_iperf_test(self) -> None:
        if self.iperf_cancel_event:
            self.iperf_cancel_event.set()
        if self.iperf_manage_cancel_event:
            self.iperf_manage_cancel_event.set()

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
            "tools": {
                "current_subtab": self.tools_inner_tab.currentIndex(),
                "arp_subnet": self.arp_subnet_edit.text().strip(),
                "arp_timeout_ms": self.arp_timeout_edit.text().strip(),
                "arp_workers": self.arp_workers_edit.text().strip(),
                "oui_mac": self.oui_mac_edit.text().strip(),
            },
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
                "use_public_server": self.iperf_use_public_server_check.isChecked(),
                "public_region": str(self.iperf_public_region_combo.currentData() or ""),
                "public_server_key": str(self.iperf_public_server_combo.currentData() or ""),
                "server": self.iperf_server_edit.text().strip(),
                "port": self.iperf_port_edit.text().strip(),
                "streams": self.iperf_streams_edit.text().strip(),
                "duration": self.iperf_duration_edit.text().strip(),
                "reverse": self.iperf_reverse_check.isChecked(),
                "udp": self.iperf_udp_check.isChecked(),
                "ipv6": self.iperf_ipv6_check.isChecked(),
            },
        }

    def restore_ui_state(self, ui_state: dict | None) -> None:
        state = dict(ui_state or {})
        if not state:
            return

        current_tab = int(state.get("current_tab", 0) or 0)
        if 0 <= current_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(current_tab)

        tools_state = state.get("tools", {})
        tools_subtab = int(tools_state.get("current_subtab", 0) or 0)
        if 0 <= tools_subtab < self.tools_inner_tab.count():
            self.tools_inner_tab.setCurrentIndex(tools_subtab)
        self.arp_subnet_edit.setText(str(tools_state.get("arp_subnet", "") or ""))
        self.arp_timeout_edit.setText(str(tools_state.get("arp_timeout_ms", "") or ""))
        self.arp_workers_edit.setText(str(tools_state.get("arp_workers", "") or ""))
        self.oui_mac_edit.setText(str(tools_state.get("oui_mac", "") or ""))

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
        self._preferred_public_iperf_region = str(iperf_state.get("public_region", "") or "")
        public_server_key = str(iperf_state.get("public_server_key", "") or "")
        self._preferred_public_iperf_key = public_server_key
        if self._preferred_public_iperf_region:
            region_index = self.iperf_public_region_combo.findData(self._preferred_public_iperf_region)
            if region_index >= 0:
                self.iperf_public_region_combo.setCurrentIndex(region_index)
        if public_server_key:
            index = self.iperf_public_server_combo.findData(public_server_key)
            if index >= 0:
                self.iperf_public_server_combo.setCurrentIndex(index)
        self.iperf_use_public_server_check.setChecked(bool(iperf_state.get("use_public_server", False)))
        self.iperf_server_edit.setText(str(iperf_state.get("server", "") or ""))
        self.iperf_port_edit.setText(str(iperf_state.get("port", self.iperf_port_edit.text()) or ""))
        self.iperf_streams_edit.setText(str(iperf_state.get("streams", self.iperf_streams_edit.text()) or ""))
        self.iperf_duration_edit.setText(str(iperf_state.get("duration", self.iperf_duration_edit.text()) or ""))
        self.iperf_reverse_check.setChecked(bool(iperf_state.get("reverse", False)))
        self.iperf_udp_check.setChecked(bool(iperf_state.get("udp", False)))
        self.iperf_ipv6_check.setChecked(bool(iperf_state.get("ipv6", False)))
        self._sync_public_iperf_target(overwrite_port=not bool(self.iperf_port_edit.text().strip()))
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
