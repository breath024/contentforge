"""ContentForge 런처 — 서버 켜고 끄는 창.

바탕화면 'ContentForge' 바로가기로 연다(pythonw 라 콘솔창 없음).
  켜기 → python app.py 를 창 없이 띄우고, 뜨면 브라우저를 연다
  끄기 → 8770 포트를 쥔 프로세스를 자식(헤드리스 Chrome)까지 통째로 끈다
         → 터미널에서 따로 켠 서버도 여기서 끌 수 있다
창을 닫으면 여기서 켠 서버는 같이 꺼진다(바깥에서 켠 건 그대로 둔다).
"""
from __future__ import annotations
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).parent
PORT = 8770  # app.py main() 과 같아야 함
URL = f"http://127.0.0.1:{PORT}"
NO_WINDOW = subprocess.CREATE_NO_WINDOW
LOG_MAX = 500

BG, PANEL, LINE = "#0b1020", "#121a2e", "#283549"
FG, MUTED = "#e7ecf5", "#94a3b8"
ON, WAIT, OFF, ACCENT, DANGER = "#86efac", "#fde047", "#64748b", "#7c3aed", "#fca5a5"
FONT = "Malgun Gothic"


def _python() -> str:
    # 런처는 pythonw 로 뜨지만 서버는 python.exe 로 — CREATE_NO_WINDOW 라 창은 안 뜬다
    p = Path(sys.executable).with_name("python.exe")
    return str(p if p.exists() else sys.executable)


def _get_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5):
            return True
    except Exception:
        return False


def port_pid() -> int | None:
    """8770 을 LISTEN 중인 PID. 상태 문자열은 로케일마다 달라서 원격주소(0.0.0.0:0)로 판정."""
    try:
        raw = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             timeout=5, creationflags=NO_WINDOW).stdout
    except Exception:
        return None
    out = raw.decode("ascii", "replace")  # 한글 윈도우는 cp949 로 찍는다. 필요한 칸은 전부 ASCII
    for line in out.splitlines():
        parts = line.split()
        if (len(parts) >= 5 and parts[1].endswith(f":{PORT}")
                and parts[2] in ("0.0.0.0:0", "[::]:0") and parts[-1].isdigit()):
            return int(parts[-1])
    return None


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=NO_WINDOW)


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.logq: queue.Queue[str] = queue.Queue()
        self.up = False          # 서버가 실제로 응답하는지
        self.ollama = False
        self.busy = False        # 끄는 중
        self.open_when_ready = False

        root.title("ContentForge")
        root.configure(bg=BG)
        root.geometry("480x440")
        root.minsize(380, 320)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        wrap = tk.Frame(root, bg=BG, padx=18, pady=16)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="ContentForge", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(wrap, text=URL, bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        st = tk.Frame(wrap, bg=PANEL, padx=14, pady=10, highlightthickness=1,
                      highlightbackground=LINE)
        st.pack(fill="x", pady=(12, 10))
        self.srv_dot, self.srv_txt = self._status_row(st, "서버")
        self.oll_dot, self.oll_txt = self._status_row(st, "Ollama")

        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill="x")
        self.b_start = self._button(btns, "▶  켜기", self.start, ACCENT, "#fff")
        self.b_stop = self._button(btns, "■  끄기", self.stop, PANEL, DANGER)
        self.b_open = self._button(btns, "브라우저 열기", self.open_browser, PANEL, FG)

        self.log = tk.Text(wrap, bg=PANEL, fg=MUTED, insertbackground=FG, relief="flat",
                           font=("Consolas", 9), height=10, wrap="word",
                           highlightthickness=1, highlightbackground=LINE,
                           padx=10, pady=8, state="disabled")
        self.log.pack(fill="both", expand=True, pady=(12, 0))

        threading.Thread(target=self._watch, daemon=True).start()
        self._tick()

    # ---- UI 조립 ----
    def _status_row(self, parent, name):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        dot = tk.Label(row, text="●", bg=PANEL, fg=OFF, font=(FONT, 11))
        dot.pack(side="left")
        tk.Label(row, text=name, bg=PANEL, fg=FG, width=7, anchor="w",
                 font=(FONT, 10, "bold")).pack(side="left", padx=(6, 0))
        txt = tk.Label(row, text="확인 중…", bg=PANEL, fg=MUTED, font=(FONT, 10))
        txt.pack(side="left")
        return dot, txt

    def _button(self, parent, text, cmd, bg, fg):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=LINE,
                      activeforeground=fg, disabledforeground="#475569", relief="flat",
                      bd=0, padx=14, pady=8, cursor="hand2", font=(FONT, 10, "bold"))
        b.pack(side="left", padx=(0, 8))
        return b

    def say(self, line: str):
        self.logq.put(line)

    # ---- 동작 ----
    def _mine(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.up:
            self.open_browser()
            return
        if self._mine():
            return
        env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        try:
            self.proc = subprocess.Popen(
                [_python(), "app.py"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        except Exception as e:
            self.say(f"[런처] 켜기 실패: {e}")
            return
        self.open_when_ready = True
        self.say("[런처] 서버 켜는 중…")
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen):
        for raw in proc.stdout:
            self.say(raw.decode("utf-8", "replace").rstrip())
        code = proc.wait()
        # taskkill /F 는 종료코드 1 — 우리가 끈 거면 에러로 보이지 않게
        if not self.busy and code not in (0, None):
            self.say(f"[런처] 서버가 스스로 멈췄어요 (코드 {code}) — 위 로그 확인")

    def stop(self):
        if self.busy:
            return
        self.busy = True
        self.say("[런처] 서버 끄는 중…")

        def work():
            pid = self.proc.pid if self._mine() else port_pid()
            if pid:
                kill_tree(pid)
            for _ in range(20):  # 포트가 풀릴 때까지
                if not _get_ok(URL + "/api/storage"):
                    break
                time.sleep(0.25)
            self.say("[런처] 꺼졌어요" if pid else "[런처] 켜진 서버가 없어요")
            self.busy = False

        threading.Thread(target=work, daemon=True).start()

    def open_browser(self):
        webbrowser.open(URL)

    def on_close(self):
        if self._mine():
            kill_tree(self.proc.pid)
        self.root.destroy()

    # ---- 상태 감시 ----
    def _watch(self):
        while True:
            self.up = _get_ok(URL + "/api/storage")
            self.ollama = _get_ok("http://127.0.0.1:11434/api/tags")
            time.sleep(1.2)

    def _tick(self):
        lines = []
        while not self.logq.empty():
            lines.append(self.logq.get_nowait())
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            extra = int(self.log.index("end-1c").split(".")[0]) - LOG_MAX
            if extra > 0:
                self.log.delete("1.0", f"{extra}.0")
            self.log.see("end")
            self.log.configure(state="disabled")

        starting = self._mine() and not self.up
        if self.busy:
            dot, txt = WAIT, "끄는 중…"
        elif self.up:
            dot, txt = ON, "켜짐" if self._mine() else "켜짐 (바깥에서 켠 서버)"
        elif starting:
            dot, txt = WAIT, "켜는 중…"
        else:
            dot, txt = OFF, "꺼짐"
        self.srv_dot.configure(fg=dot)
        self.srv_txt.configure(text=txt)
        self.oll_dot.configure(fg=ON if self.ollama else DANGER)
        self.oll_txt.configure(text="연결됨" if self.ollama
                               else "꺼짐 — 카피 생성이 안 돼요 (Ollama 앱 실행)")

        self.b_start.configure(state="disabled" if (self.up or starting or self.busy) else "normal")
        self.b_stop.configure(state="normal" if ((self.up or starting) and not self.busy) else "disabled")
        self.b_open.configure(state="normal" if self.up else "disabled")

        if self.up and self.open_when_ready:
            self.open_when_ready = False
            self.open_browser()
        self.root.after(300, self._tick)


if __name__ == "__main__":
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
