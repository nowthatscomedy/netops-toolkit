# NetOps Toolkit

Windows 10/11 환경의 현장 네트워크 엔지니어를 위한 PySide6 기반 통합 네트워크 도구입니다.  
인터페이스 전환, IP 설정, 진단, 무선 상태 확인, `iperf3` 실행, GitHub 릴리즈 기반 업데이트 확인까지 하나의 GUI에서 처리하는 것을 목표로 합니다.

## 주요 기능

### 인터페이스 관리

- Windows 네트워크 어댑터 목록 조회
- DHCP / 수동 IP 전환
- 게이트웨이 / DNS 적용
- 저장된 IP 프로필 저장, 수정, 삭제, 적용
- 관리자 권한 필요 작업 안내

### 진단

- 멀티 Ping
- TCPing
- `nslookup`
- `tracert / pathping`
- `ipconfig /all`, `route print`, `arp -a`, DNS 캐시 비우기
- 결과 표 CSV 저장
- 선택 항목별 로그 저장

### 무선

- 현재 Wi-Fi 연결 상태 조회
- SSID / BSSID / 채널 / 대역 / 신호 / 수신 속도 / 송신 속도 표시
- 자동 새로고침
- 연결 변화 로그

### iperf3

- 클라이언트 / 서버 모드 실행
- 프로그램 폴더, `winget` 설치본, 시스템 PATH의 `iperf3` 자동 탐색
- `winget` 기반 설치 / 업데이트 지원
- 현재 앱이 실제로 사용하는 `iperf3` 경로와 버전 표시

### 업데이트

- GitHub Releases 기반 새 버전 확인
- 설치 파일 SHA-256 검증 후 실행
- 시작 시 자동 확인 옵션 제공
- 사전배포(prerelease) 포함 여부 선택 가능
- 업데이트 채널은 프로그램 내부에 고정되어 있어 사용자가 잘못 바꾸지 않도록 설계

## 프로젝트 구조

```text
netops-toolkit/
  main.py
  requirements.txt
  README.md
  app/
    app_state.py
    main_window.py
    models/
    services/
    ui/
      dialogs/
      tabs/
    utils/
  config/
    app_config.json
    ip_profiles.json
    vendor_presets.json
  logs/
    .gitkeep
    exports/
  installer/
  scripts/
  .github/
    workflows/
```

## 실행 방법

### 1. 가상환경 생성

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 패키지 설치

```powershell
pip install -r requirements.txt
```

### 3. 실행

```powershell
python main.py
```

## 설정 및 데이터 저장 위치

실행 위치에 따라 설정/로그 저장 위치가 달라집니다.

- 일반 폴더에서 실행하는 경우
  - 보통 프로그램 폴더 내부를 그대로 사용
- `C:\Program Files` 아래에 설치된 경우
  - 쓰기 가능한 사용자 경로로 자동 전환
  - 기본 경로: `%LOCALAPPDATA%\NetOps Toolkit`

주요 파일:

- 앱 설정: [config/app_config.json](/C:/Users/PC/Desktop/python/netops-toolkit/config/app_config.json)
- IP 프로필: [config/ip_profiles.json](/C:/Users/PC/Desktop/python/netops-toolkit/config/ip_profiles.json)
- 로그: [logs/app.log](/C:/Users/PC/Desktop/python/netops-toolkit/logs/app.log)

## 업데이트 방식

이 프로그램은 GitHub Releases를 사용해 새 버전을 확인합니다.

- 사용자는 설정 탭에서 저장소 이름이나 설치 파일 규칙을 바꾸지 않습니다.
- 업데이트 채널은 프로그램 내부에 고정되어 있습니다.
- 새 버전이 있으면 설치 파일을 다운로드한 뒤 SHA-256 검증을 수행합니다.
- 검증이 완료된 경우에만 설치 프로그램을 실행합니다.

현재 기본 배포 채널:

- 저장소: `nowthatscomedy/netops-toolkit`
- 설치 파일 패턴: `NetOpsToolkit-setup.*\.exe$`

## iperf3 안내

### 실행 파일 탐색 순서

앱은 아래 순서로 `iperf3`를 찾습니다.

1. 프로그램 폴더의 `iperf3.exe`
2. `winget` 관리형 설치 경로
3. 시스템 PATH

### winget 설치 / 업데이트

Windows에서는 앱 내부에서 `winget` 패키지로 `iperf3`를 설치하거나 업데이트할 수 있습니다.

- 패키지 ID: `ar51an.iPerf3`
- 최신 버전이면 버튼이 비활성화됩니다.
- 상태 영역에 현재 사용 경로와 버전이 표시됩니다.

참고:

- ESnet 공식 릴리스는 현재 Windows 실행 파일을 직접 제공하지 않습니다.
- 그래서 Windows 환경에서는 `winget` 기반 설치 경로를 함께 지원합니다.

## 관리자 권한이 필요한 기능

다음 기능은 관리자 권한으로 실행하는 것이 권장됩니다.

- DHCP 적용
- 수동 IP 적용
- 게이트웨이 / DNS 변경
- 어댑터 관련 일부 고급 설정 적용
- 일부 DNS 캐시 비우기 작업

다음 기능은 보통 관리자 권한 없이도 사용할 수 있습니다.

- 인터페이스 조회
- Ping / TCPing
- `nslookup`
- `tracert / pathping`
- 무선 상태 조회
- `iperf3`
- 업데이트 확인

## 배포 및 패키징

### PyInstaller 예시

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name NetOpsToolkit ^
  --add-data "config;config" ^
  --add-data "logs;logs" ^
  main.py
```

### 권장 릴리즈 빌드

이 저장소에는 Windows 설치 파일 빌드 스크립트와 GitHub Actions 워크플로가 포함되어 있습니다.

- [scripts/build_release.ps1](/C:/Users/PC/Desktop/python/netops-toolkit/scripts/build_release.ps1)
  - PyInstaller 빌드
  - 샘플 설정만 포함
  - Inno Setup 설치 파일 생성
- [installer/netops-toolkit.iss](/C:/Users/PC/Desktop/python/netops-toolkit/installer/netops-toolkit.iss)
  - 설치 프로그램 생성 스크립트
- [scripts/publish_release.ps1](/C:/Users/PC/Desktop/python/netops-toolkit/scripts/publish_release.ps1)
  - GitHub Release 생성/업데이트 및 설치 파일 업로드
- [.github/workflows/release.yml](/C:/Users/PC/Desktop/python/netops-toolkit/.github/workflows/release.yml)
  - `main` 푸시 또는 수동 실행 시 릴리즈 빌드/업로드

### 로컬 빌드 예시

```powershell
pip install -r requirements.txt
pip install pyinstaller

# Inno Setup 6 필요
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Version 1.0.5 -Clean
```

## 릴리즈 운영 흐름

권장 흐름:

1. [app/version.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/version.py) 버전 수정
2. 커밋 후 `main` 푸시
3. GitHub Actions에서 설치 파일 빌드
4. GitHub Release 업로드
5. 사용자 앱에서 업데이트 확인

사전배포 버전을 배포하려면:

1. [app/version.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/version.py)를 예: `1.0.5-beta.1` 형식으로 변경
2. `main`에 푸시
3. GitHub Actions가 해당 태그를 prerelease로 발행
4. 앱에서 `사전 배포 포함(prerelease)` 옵션을 켠 사용자만 해당 버전 확인 가능

## 아키텍처 요약

### UI 계층

- [app/main_window.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/main_window.py)
  - 메인 창, 상태 표시, 하단 로그 도크
- [app/ui/tabs/interface_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/interface_tab.py)
  - 인터페이스/IP 작업
- [app/ui/tabs/diagnostics_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/diagnostics_tab.py)
  - 진단, `iperf3`
- [app/ui/tabs/wireless_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/wireless_tab.py)
  - 무선 상태
- [app/ui/tabs/settings_tab.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/ui/tabs/settings_tab.py)
  - 업데이트 옵션, 경로 바로가기

### 서비스 계층

- [app/services/network_interface_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/network_interface_service.py)
  - 어댑터 조회, DHCP/수동 IP 적용
- [app/services/powershell_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/powershell_service.py)
  - 공통 PowerShell 실행
- [app/services/ping_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/ping_service.py)
  - 멀티 Ping
- [app/services/tcp_check_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/tcp_check_service.py)
  - TCPing
- [app/services/dns_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/dns_service.py)
  - DNS 조회
- [app/services/trace_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/trace_service.py)
  - `tracert`, `pathping`, 보조 도구
- [app/services/wireless_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/wireless_service.py)
  - 무선 상태 파싱
- [app/services/iperf_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/iperf_service.py)
  - `iperf3` 실행, 설치 경로 탐색, `winget` 관리
- [app/services/update_service.py](/C:/Users/PC/Desktop/python/netops-toolkit/app/services/update_service.py)
  - 업데이트 확인, 다운로드, 검증, 설치 실행

## 확장 포인트

- 고객사별 프로필 팩
- 장비별 초기 접속 템플릿
- 보고서 자동 생성
- MAC OUI 벤더 조회
- 업데이트 채널 분리(정식/베타)
- 추가 네트워크 도구 통합

## 검증

현재 코드 기준으로 최소 정적 검증은 아래처럼 수행할 수 있습니다.

```powershell
python -m compileall main.py app
```

GUI 동작은 실제 Windows 환경과 설치된 네트워크 구성, 권한 상태에 따라 달라질 수 있습니다.
