# J.A.R.V.I.S. OS v0.1.0

현재 Windows에서 안전하게 실행하는 데스크톱 HUD 프로토타입입니다. Linux 부팅 이미지, 디스크 파티션, 부트로더는 포함하지 않으며 시스템 설정을 변경하지 않습니다.

## 기능

- PySide6 전체 화면 HUD 셸 (F11로 전체 화면 전환, Esc로 종료)
- 인간형 비율의 하드서피스 슈트 3D 홀로그램 (절제된 헬멧·몸통·팔다리 장갑판, 깊이 가림 처리, 가장자리 청록 반사광과 홀로라인)
- `홀로그램 전체 화면` 버튼으로 선택한 모델만 전체 화면에 표시하고, `HUD로 돌아가기` 또는 `Esc`로 복귀
- 홀로그램 모델 전환 버튼으로 슈트, 손목 웹슈터, 아크 리액터, 아이언맨 손을 순환해 회전·확대해서 볼 수 있음
- 별도 OpenGL/3D 패키지 없이 PySide6 페인터로 로컬 렌더링해 그래픽 드라이버 의존성을 낮춤
- 한국어 기본 화면과 EN/KO 언어 전환
- 마이크 음성을 다국어 오프라인 Whisper tiny로 인식하고 말이 끝나면 자동 종료 (최대 15초)
- JARVIS AI와 로컬 명령 답변을 한국어/영어 오프라인 음성으로 읽어 주며 음성 응답 토글 제공
- 음성 응답 전 `J.A.R.V.I.S.` 표기를 한국어 문장에서는 `자비스`로 바꿔 철자별로 끊어 읽지 않게 처리
- Ollama가 꺼져 있으면 JARVIS가 설치 경로를 찾아 백그라운드 서버를 시작하고, 앱 종료 시 JARVIS가 시작한 서버만 종료
- 기본 남성 음성 프리셋 M1 및 1.5배 속도 사용 (환경 변수로 조정 가능)
- 음성 인식 결과를 명령 라우터 또는 Ollama 채팅으로 바로 전달
- `대화 초기화` / `clear chat`으로 화면 기록과 AI 대화 문맥 지우기
- Windows IME가 영문 키 이벤트만 보낼 때를 위한 앱 내 두벌식 한글 조합 입력
- 한국어 문장형 요청: 인사, 시간, CPU/RAM 상태, 가동 시간, 도움말
- CPU 및 메모리 사용률 표시 (1초 간격)
- 헤더 RAM 배지에 사용 가능 메모리를 GiB 단위로 표시하고, 2.5GiB 미만이면 경고 색상으로 표시
- 메모리 카드에 전체 사용량, 사용 가능량, JARVIS 프로세스 사용량을 분리해 표시
- 화면 분석을 끄면 Ollama 비전 모델을 메모리에서 해제하고, 켜져 있는 동안은 반복 분석을 위해 모델을 유지
- 음성 인식 Whisper 모델은 발화가 끝나면 메모리에서 해제하며, TTS 모델도 음성 출력 후 해제
- 각 모니터 카드에 최근 60초 사용률 그래프 표시
- 한국어 명령: `도움말`, `상태`, `시간`, `가동시간`, `메모장 열기`, `계산기 열기` (영어 명령도 지원)
- 명령은 셸을 통하지 않으며 앱 실행은 로컬 보안 allowlist를 거침
- 자유 질문은 로컬 Ollama의 `qwen2.5:3b` 모델로 처리 (클라우드/API 키 불필요)
- 로컬 AI가 응답하거나 음성을 생성하는 동안 홀로그램 렌더링 부하를 낮추고, Ollama CPU 스레드를 논리 코어 절반(최대 4개)으로 제한
- 사용자가 켠 경우에만 주 화면을 15초마다 캡처해 로컬 Ollama 비전 모델로 한국어 설명 (기본 꺼짐, 이미지 파일 저장 없음)
- 화면 분석은 여유 메모리 2.5GiB 미만이면 시작하지 않으며, 화면 분석 토글을 끄면 캡처 중지
- 선택 손짓 제어: 엄지 위=확대, 엄지 아래=축소, 열린 손바닥 쓸기=회전, L자 손짓=손 위치로 시점 이동, 주먹=스캔 정지, V자=초기화
- 손짓 제어는 기본 꺼짐이며 켠 뒤에만 카메라를 열고, 영상 프레임을 저장하거나 전송하지 않음
- Ollama 응답은 백그라운드 스레드에서 처리해 HUD 입력과 모니터링이 멈추지 않음
- 실행 시 Ollama 서버와 설정 모델 연결 상태를 확인해 HUD에 표시
- 대화창에 질문과 답변을 이어서 표시하고, 최근 기록은 앱 메모리에만 유지 (종료 시 삭제)
- 음성, AI, 데스크톱, 보안 엔진의 모듈 구조
- 모니터링 정보는 화면 표시용이며 자동으로 시스템을 제어하지 않음

## 사전 요구사항

- Windows 10/11
- Python 3.10 이상 (확인된 환경: Python 3.13.3)
- VS Code (선택)
- Git (선택)
- 패키지 설치 시 인터넷 연결
- 자유 대화 기능 사용 시 Ollama 데스크톱 앱/서버와 로컬 모델 필요
- 음성 입출력은 `sounddevice`, `faster-whisper`, `supertonic`을 사용하고, 최초 모델 준비 시 인터넷 연결과 `.models` 저장 공간 필요
- 손짓 제어는 선택 의존성 `mediapipe`(카메라용 OpenCV 포함) 및 첫 실행 시 내려받는 `.models` 인식 모델 필요

현재 확인 결과 VS Code, Python 3.13.3, Git, PySide6 6.12.0, psutil 7.2.2가 준비되어 있습니다. Ollama 0.40.16과 로컬 모델 `qwen2.5:3b`도 확인했고, 앱에서 사용하는 로컬 chat API 응답을 확인했습니다. WSL 명령은 있으나 Ubuntu 배포판은 확인되지 않았습니다. 기존 Windows 음성 입력은 한국어 인식기를 찾지 못했으며, 이 프로젝트는 OS 언어 설정 대신 별도의 오프라인 Whisper 모델을 사용합니다. OS/가상화 상세 점검은 이 실행 환경의 권한 오류로 확인하지 못했습니다.

## 로컬 AI (Ollama)

### 손짓으로 홀로그램 조작

손짓 제어를 사용하려면 프로젝트 가상환경에서 선택 패키지를 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gestures.txt
```

HUD의 **손짓 제어** 버튼을 눌러 켜면 기본 카메라가 연결되고, 첫 실행 때 손짓 모델을 `.models\gesture_recognizer.task`에 내려받습니다. 열린 손바닥 쓸기는 회전, L자 손짓은 손 위치에 맞춰 부드럽게 시점을 이동합니다. 엄지 위/아래는 확대/축소, 주먹은 스캔 정지, V자는 초기화입니다. 버튼을 끄면 카메라를 해제합니다. 카메라 접근이 거부되거나 장치를 사용할 수 없으면 상태 문구에 오류가 표시됩니다.

Ollama 서버가 실행 중이면 JARVIS 입력창에 질문을 입력해 보세요. 기본 주소는 `http://127.0.0.1:11434`이며 기본 모델은 `qwen2.5:3b`입니다. 시간, 시스템 상태, 도움말, 대화 초기화, 메모장/계산기 같은 허용 명령은 로컬에서 먼저 처리합니다. 나머지 문장은 Ollama로 전달됩니다.

음성 버튼을 누르면 말이 끝날 때까지 최대 15초 마이크를 듣고, Whisper가 언어를 자동 판별합니다. 변환된 문장은 대화창에 남고 명령/AI 라우터로 전달됩니다. JARVIS 답변은 기본으로 로컬 음성 출력되며 `음성 응답 켬/끔` 버튼으로 조절할 수 있습니다. Whisper와 Supertonic 모델은 첫 사용 시 `.models` 폴더에 내려받습니다. 오디오 인식, 음성 생성, 재생은 로컬 PC에서 처리됩니다.

참고 음성과 더 비슷하게 들리도록 기본 음성 프리셋은 `M1`, 속도는 `1.5`로 설정했습니다. 시작 전에 환경 변수로 바꿀 수 있습니다.

```powershell
$env:JARVIS_TTS_VOICE = "M1"
$env:JARVIS_TTS_SPEED = "1.5"
python -m jarvis_os
```

JARVIS가 설치된 Ollama의 로컬 서버를 백그라운드로 자동 시작하므로 Ollama 앱을 먼저 열 필요가 없습니다. JARVIS가 시작한 서버는 앱 종료 시 함께 종료합니다. 기본 `qwen2.5:3b` 모델이 설치되어 있어야 하며, 모델을 바꾸려면 실행 전에 환경 변수를 지정할 수 있습니다.

```powershell
$env:JARVIS_OLLAMA_MODEL = "qwen2.5:3b"
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
python -m jarvis_os
```

화면 설명은 별도 비전 모델이 필요합니다. 기본 모델은 `moondream:latest`이며, 모델을 직접 준비한 뒤 HUD의 **화면 분석** 버튼을 켜세요. 설치 예시는 `ollama pull moondream`입니다. 이 모델은 약 1.7GB를 차지합니다. 이 명령은 Ollama 모델을 사용자 PC에 내려받으므로, 디스크 공간과 메모리 여유를 확인한 뒤 실행하세요. 여유 RAM이 2.5GiB 미만이면 JARVIS가 분석을 시작하지 않습니다. 모델이 없거나 Ollama가 꺼져 있으면 화면을 캡처하지 않습니다.

화면 분석 중에는 응답을 빠르게 하기 위해 비전 모델이 Ollama 메모리에 남습니다. 화면 분석을 끄면 JARVIS가 Ollama에 모델 해제를 요청합니다. PC 메모리가 부족한 경우 앱의 상단 RAM 배지와 메모리 카드가 주황색으로 바뀝니다. 작업 중인 창은 JARVIS가 닫지 않으므로, 메모리를 확보하려면 직접 저장한 후 사용하지 않는 앱을 닫아 주세요.

모델을 바꾸려면 실행 전에 다음과 같이 지정합니다.

```powershell
$env:JARVIS_VISION_MODEL = "moondream:latest"
python -m jarvis_os
```

## 설치 및 실행 (PowerShell)

```powershell
cd C:\Users\user\Documents\Codex\JARVIS-OS
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m jarvis_os
```

PowerShell 실행 정책 때문에 활성화가 막히면 활성화 단계는 건너뛰고 아래처럼 가상환경 Python을 직접 실행하세요.

```powershell
cd C:\Users\user\Documents\Codex\JARVIS-OS
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m jarvis_os
```

종료는 `Esc` 또는 창 닫기입니다. `F11`로 전체 화면과 창 모드를 바꿀 수 있습니다. 설치가 완료되지 않아도 시스템에는 아무 변경이 없습니다.

## VS Code에서 열기

```powershell
code C:\Users\user\Documents\Codex\JARVIS-OS
```

VS Code에서 `.venv`를 Python 인터프리터로 선택하면 됩니다.

## 구조

```text
jarvis_os/
  __main__.py
  app.py
  ui/main_window.py
  ui/suit3d.py
  engines/
    system_monitor.py
    voice.py
    speech_output.py
    ai.py
    desktop.py
    security.py
    gesture.py
requirements.txt
requirements-gestures.txt
```

Linux 기반 부팅 OS 개발은 별도 단계입니다. Ubuntu/가상화 설치 여부와 대상 장치, 백업을 확인하고 별도 가상 머신에서 검증한 뒤에만 시스템 수준 작업을 검토합니다. 이 v0.1.0은 기존 J.A.R.V.I.S. 프로젝트와 분리되어 있습니다.
