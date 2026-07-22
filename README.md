# PC 사용 시간 모니터

키보드/마우스 입력을 감지하여 실제 PC 활성 사용 시간을 자동으로 기록하고 집계합니다.

---

## 동작 원리

| 구분 | macOS | Windows |
|---|---|---|
| 유휴 감지 API | `ioreg IOHIDSystem HIDIdleTime` | `GetLastInputInfo` (User32.dll) |
| 언어 | Python 3 (표준 라이브러리 + subprocess) | Python 3 (ctypes) |

일정 시간(기본 60초) 동안 마우스/키보드 입력이 없으면 **유휴(idle)** 상태로 전환하여 해당 세션을 종료 기록합니다. 입력이 재개되면 새 세션을 시작합니다.

```
[활성] ──── 60초 무입력 ────▶ [유휴] ──── 입력 재개 ────▶ [활성]
              ↓                                              ↓
         세션 종료 기록                                세션 시작 기록
```

---

## 설치

별도 패키지 설치 없이 Python 3 표준 라이브러리만 사용합니다.

```bash
python3 --version   # 3.10 이상 권장
```

---

## 사용법

### 모니터링 시작

```bash
# 기본값으로 시작 (유휴 60초)
python3 tracker.py

# 유휴 임계값을 120초로 지정하여 시작
python3 tracker.py --idle 120

# 유휴 임계값 120초, 폴링 주기 10초
python3 tracker.py --idle 120 --poll 10
```

실행 중 출력 예시:
```
Tracker started  |  idle threshold=60s  poll=5s  log=usage_log.json

  Commands while running:
    <number>   — set idle threshold in seconds  (e.g. 120)
    set <n>    — same as above
    status     — show current state and settings
    help       — show this message
    quit       — stop tracker

[09:01:00] Active  — session started
[10:32:15] Idle    — today's active time: 01:31:15
[10:45:03] Active  — session started
```

### 실행 중 유휴 임계값 동적 변경

트래커가 실행 중인 상태에서 터미널에 직접 입력하면 즉시 반영됩니다.

```
120        # 유휴 임계값을 120초로 변경
set 30     # 유휴 임계값을 30초로 변경
status     # 현재 상태 및 설정 확인
help       # 명령어 목록 출력
quit       # 트래커 종료
```

종료는 `Ctrl-C` 또는 `quit` 입력 시 현재 세션을 저장 후 당일 요약을 출력합니다.

### 리포트 출력

```bash
python3 tracker.py --report
# 또는
python3 tracker.py -r
```

출력 예시:
```
─── Usage report ───────────────────────────────────
  2026-07-20  |  sessions:   4  |  active: 05:12:30
  2026-07-21  |  sessions:   6  |  active: 07:44:10
  2026-07-22  |  sessions:   3  |  active: 03:05:55
────────────────────────────────────────────────────
```

---

## 설정

### CLI 옵션 (시작 시)

| 옵션 | 단축 | 기본값 | 설명 |
|---|---|---|---|
| `--idle <초>` | `-i` | `60` | 유휴 판정 임계값 (초) |
| `--poll <초>` | `-p` | `5` | 유휴 상태 확인 주기 (초) |
| `--report` | `-r` | — | 누적 리포트 출력 후 종료 |

### 실행 중 동적 변경

| 입력 | 설명 |
|---|---|
| `<숫자>` 또는 `set <숫자>` | 유휴 임계값을 즉시 변경 |
| `status` | 현재 상태(활성/유휴), 임계값, 오늘 활성 시간 출력 |
| `quit` | 트래커 정상 종료 |

### 코드 기본값 변경

`tracker.py` 상단 상수를 수정하면 CLI 기본값이 바뀝니다.

```python
DEFAULT_IDLE_THRESHOLD_SEC = 60    # --idle 미지정 시 기본값
DEFAULT_POLL_INTERVAL_SEC  = 5     # --poll 미지정 시 기본값
LOG_FILE = Path(__file__).parent / "usage_log.json"
```

---

## 로그 파일 형식

`usage_log.json`에 날짜별로 세션이 누적 저장됩니다.

```json
{
  "2026-07-22": {
    "sessions": [
      {
        "start":    "2026-07-22T09:01:00",
        "end":      "2026-07-22T10:32:15",
        "duration": 5475.0
      }
    ],
    "total_active_sec": 5475.0
  }
}
```

---

## 파일 구성

```
serveilance/
├── tracker.py       # 메인 스크립트
├── usage_log.json   # 자동 생성되는 사용 기록 (gitignore 권장)
└── README.md
```

---

## 주의사항

- **macOS**: `ioreg` 명령어는 기본 내장되어 있어 별도 설치 불필요합니다.
- **Windows**: `ctypes`는 Python 표준 라이브러리에 포함되어 있습니다.
- **Linux**: 현재 미지원입니다. `xprintidle` 등 별도 구현이 필요합니다.
- 절전/잠금 화면 상태에서는 HID 입력이 발생하지 않으므로 자동으로 유휴로 처리됩니다.
