"""Colored print helpers for the backend terminal."""
import sys, os

# Enable ANSI on Windows 10+
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

class C:
    RESET   = "\033[0m"
    DIM     = "\033[2m"
    BOLD    = "\033[1m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    GRAY    = "\033[90m"
    BRED    = "\033[91m"
    BGREEN  = "\033[92m"
    BYELLOW = "\033[93m"

def _tag(color: str, label: str) -> str:
    return f"{color}{C.BOLD}[{label}]{C.RESET}"

def log_ai(msg: str):       print(f"{_tag(C.MAGENTA, 'AI')} {msg}")
def log_ws(msg: str):       print(f"{_tag(C.BLUE,    'WS')} {msg}")
def log_db(msg: str):       print(f"{_tag(C.YELLOW,  'DB')} {msg}")
def log_audio(msg: str):    print(f"{_tag(C.CYAN,    'AUDIO')} {msg}")
def log_incident(msg: str): print(f"{_tag(C.BRED,    'INCIDENT')} {msg}")
def log_app(msg: str):      print(f"{_tag(C.GREEN,   'APP')} {msg}")
def log_decay(msg: str):    print(f"{_tag(C.GRAY,    'DECAY')} {msg}")
def log_clf(msg: str):      print(f"{_tag(C.MAGENTA, 'CLF')} {msg}")

def log_vad(is_speech: bool, duration: float, rms: float):
    """VAD: green for speech, gray for silence — easy to scan."""
    if is_speech:
        print(f"{_tag(C.BGREEN, 'VAD')} {C.BGREEN}speech=True{C.RESET}  "
              f"duration={duration:.1f}s  rms={rms:.4f}")
    else:
        print(f"{C.GRAY}[VAD] speech=False  duration={duration:.1f}s  rms={rms:.4f}{C.RESET}")

def log_warn(prefix: str, msg: str):
    print(f"{C.BYELLOW}{C.BOLD}[{prefix}]{C.RESET} {C.YELLOW}{msg}{C.RESET}")

def log_err(prefix: str, msg: str):
    print(f"{C.BRED}{C.BOLD}[{prefix}]{C.RESET} {C.RED}{msg}{C.RESET}")
