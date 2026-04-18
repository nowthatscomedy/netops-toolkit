# NetOps Toolkit

Windows 10/11 환경에서 현장 네트워크 작업을 빠르게 처리할 수 있도록 만든 PySide6 기반 GUI 도구입니다.  
하나의 앱에서 인터페이스 설정, 저장된 IP 프로필 적용, 진단 도구 실행, Wi-Fi 상태 확인, `iperf3` 테스트, GitHub 릴리스 기반 업데이트 확인까지 처리할 수 있습니다.

## 주요 기능

### 인터페이스 관리

- Windows 네트워크 어댑터 목록 조회
- DHCP / 고정 IP 전환
- 게이트웨이 / DNS 적용
- 현재 설정을 IP 프로필로 저장
- 저장된 IP 프로필 추가, 수정, 삭제, 재적용

### 진단 도구

- 서브넷 계산기
- ARP 스캔
- MAC / BSSID 기반 OUI 벤더 조회
- 멀티 Ping
- TCPing
- `nslookup`
- `tracert` / `pathping`
- `ipconfig /all`, `route print`, `arp -a`, DNS 캐시 비우기
- Ping / TCP 결과 CSV 내보내기
- 선택한 Ping / TCP 로그 개별 저장

### 무선 진단

- 현재 Wi-Fi 연결 상태 조회
- SSID / BSSID / 채널 / 대역 / 신호 / 송수신 속도 표시
- 주변 AP 스캔
- 밴드 / 보안 / 검색어 / 정렬 기준 필터
- OUI 캐시 기반 AP 벤더 표시
- 자동 새로고침 및 연결 변화 로그

### `iperf3`

- 클라이언트 / 서버 모드 실행
- 프로그램 폴더, `winget` 설치본, 시스템 PATH에서 `iperf3` 자동 탐색
- `winget` 기반 설치 / 업데이트 지원
- 공개 `iperf3` 서버 목록 캐시 및 새로고침 지원
- 현재 앱이 실제로 사용하는 `iperf3` 경로와 버전 표시

### 업데이트 / 운영 편의 기능

- GitHub Releases 기반 새 버전 확인
- 설치 파일 SHA-256 검증 후 실행
- 시작 시 자동 업데이트 확인 옵션
- 사전 배포(prerelease) 포함 여부 설정
- UI 상태와 주요 설정 자동 저장
- 설정 / 로그 폴더 바로 열기

## 시스템 요구사항

- Windows 10 또는 Windows 11
- Python 3.11 권장
- PowerShell 사용 가능 환경
- 일부 기능에는 관리자 권한 필요
- 업데이트 확인, OUI 캐시 갱신, 공개 `iperf3` 서버 목록 갱신에는 인터넷 연결 필요

## 빠른 시작

### 1. 가상환경 생성

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 의존성 설치

```powershell
pip install -r requirements.txt
```

### 3. 앱 실행

```powershell
python main.py
```

## 관리자 권한이 필요한 작업

다음 작업은 관리자 권한으로 실행하는 것이 좋습니다.

- DHCP 적용
- 고정 IP 적용
- 게이트웨이 / DNS 변경
- 일부 어댑터 고급 설정 적용
- 일부 DNS 캐시 비우기 작업

다음 작업은 일반 권한에서도 대체로 사용할 수 있습니다.

- 인터페이스 조회
- Ping / TCPing / `nslookup`
- `tracert` / `pathping`
- 서브넷 계산
- ARP 결과 조회
- Wi-Fi 상태 / 주변 AP 스캔
- `iperf3`
- 업데이트 확인

## 설정과 데이터 저장 위치

앱은 실행 위치에 따라 설정과 로그를 저장하는 위치를 자동으로 결정합니다.

- 일반 폴더에서 실행하면 보통 프로젝트(또는 실행 파일) 폴더를 그대로 사용합니다.
- `C:\Program Files` 같은 보호된 경로에 설치되어 있으면 `%LOCALAPPDATA%\NetOps Toolkit` 아래로 자동 전환합니다.

실행 중 생성되거나 사용되는 주요 파일:

- `config/app_config.json`
  - 기본 앱 설정, 업데이트 설정, UI 상태 저장
- `config/ip_profiles.json`
  - 저장된 IP 프로필
- `config/vendor_presets.json`
  - 레거시 프리셋 마이그레이션 입력 파일
- `config/public_iperf_servers_cache.json`
  - 공개 `iperf3` 서버 목록 캐시
- `config/oui_cache.json`
  - IEEE OUI 벤더 캐시
- `logs/app.log`
  - 앱 실행 로그
- `logs/exports/`
  - CSV / 로그 내보내기 결과

첫 실행 시 런타임 `config/`가 비어 있으면 저장소의 기본 `config/` 파일을 복사해 초기화합니다.

## 업데이트 방식

앱은 GitHub Releases를 사용해 새 버전을 확인합니다.

- 기본 저장소: `nowthatscomedy/netops-toolkit`
- 기본 설치 파일 패턴: `NetOpsToolkit-setup.*\.exe$`
- 설치 파일은 다운로드 후 SHA-256 검증을 통과해야만 실행됩니다.
- 정식 배포만 볼지, 사전 배포까지 포함할지 설정에서 선택할 수 있습니다.

## `iperf3` 동작 방식

앱은 아래 순서로 `iperf3` 실행 파일을 찾습니다.

1. 프로그램 폴더의 `iperf3.exe`
2. `winget` 관리형 설치 경로
3. 시스템 PATH

Windows 환경에서는 앱 내부에서 `winget` 패키지 `ar51an.iPerf3`를 사용해 설치 또는 업데이트할 수 있습니다.

또한 공개 서버 목록은 `R0GGER/public-iperf3-servers` 기반 JSON 내보내기를 사용해 캐시하며, 오프라인일 때는 마지막 캐시를 재사용합니다.

## 프로젝트 구조

```text
netops-toolkit/
  main.py
  requirements.txt
  README.md
  app/
    app_state.py
    main_window.py
    version.py
    models/
    services/
    ui/
      common/
      dialogs/
      tabs/
    utils/
  assets/
    icons/
  config/
  installer/
  scripts/
  tests/
  .github/
    workflows/
```

## 테스트

기본 테스트 실행:

```powershell
python -m pytest
```

간단한 정적 검증:

```powershell
python -m compileall main.py app
```

테스트는 주로 다음 영역을 확인합니다.

- 유효성 검사 로직
- 무선 출력 파서
- 일부 UI 상태 저장 / 복원 규약
- 버전 문자열 계약

## 빌드와 배포

### 로컬 설치 파일 빌드

```powershell
pip install -r requirements.txt
pip install pyinstaller

# Inno Setup 6 필요
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Version 1.0.5 -Clean
```

### 관련 스크립트

- `scripts/build_release.ps1`
  - PyInstaller 번들 생성
  - 런타임용 `config/`, `logs/`, 아이콘 포함
  - Inno Setup 설치 파일 생성
- `installer/netops-toolkit.iss`
  - Windows 설치 프로그램 생성 스크립트
- `scripts/publish_release.ps1`
  - GitHub Release 생성 / 갱신 및 설치 파일 업로드
- `.github/workflows/release.yml`
  - `main` 브랜치 푸시 또는 수동 실행 시 릴리스 빌드 / 업로드

### 릴리스 운영 흐름

1. `app/version.py` 버전 수정
2. 변경사항 커밋 후 `main` 푸시
3. GitHub Actions에서 설치 파일 빌드
4. GitHub Release 업로드
5. 사용자 앱에서 업데이트 확인

사전 배포를 만들 때는 `app/version.py`를 예: `1.0.5-beta.1` 형식으로 올리면 워크플로가 prerelease로 발행할 수 있습니다.

## 참고

- GUI 동작은 실제 Windows 네트워크 구성, 권한 상태, 설치된 도구에 따라 달라질 수 있습니다.
- OUI 캐시와 공개 `iperf3` 서버 캐시는 네트워크 상황에 따라 갱신이 실패할 수 있으며, 가능한 경우 기존 캐시를 재사용합니다.
