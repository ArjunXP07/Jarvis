

import os, sys, subprocess, datetime, webbrowser
import time, threading, re, json, textwrap

# ── SpeechRecognition ─────────────────────────────────────────────
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    print("[WARN] SpeechRecognition not installed — voice input disabled.")
    SR_AVAILABLE = False

# ── pyttsx3 ───────────────────────────────────────────────────────
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    print("[WARN] pyttsx3 not installed — voice output disabled.")
    TTS_AVAILABLE = False

# ── Gemini ────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
except ImportError:
    print("[ERROR] Run: pip install google-generativeai")
    sys.exit(1)

# ── Web ───────────────────────────────────────────────────────────
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] Run: pip install requests beautifulsoup4")
    sys.exit(1)

try:
    import wikipedia
    WIKI_OK = True
except ImportError:
    WIKI_OK = False


# ══════════════════════════════════════════════════════════════════
#  CONFIG  — ⚠️  Paste your NEW API key here after regenerating
# ══════════════════════════════════════════════════════════════════
class Config:
    GEMINI_API_KEY : str  = "API"
    WAKE_WORD      : str  = "jarvis"

    # ── Mic tuning (Windows fix) ──────────────────────────────────
    ENERGY_THRESHOLD    : int   = 200    # lower = more sensitive
    DYNAMIC_ENERGY      : bool  = True
    PAUSE_THRESHOLD     : float = 0.8
    AMBIENT_CALIBRATION : float = 1.5
    PHRASE_LIMIT_WAKE   : int   = 4
    PHRASE_LIMIT_COMMAND: int   = 12

    # ── Voice output ──────────────────────────────────────────────
    VOICE_RATE   : int   = 170
    VOICE_VOLUME : float = 1.0

    # ── Windows App Paths ─────────────────────────────────────────
    APP_PATHS : dict = {
        "vscode"     : "code",
        "chrome"     : "chrome",
        "notepad"    : "notepad",
        "spotify"    : "spotify",
        "calculator" : "calc",
        "terminal"   : "cmd",
        "explorer"   : "explorer",
        "word"       : "winword",
        "excel"      : "excel",
        "powerpoint" : "powerpnt",
    }

    SYSTEM_PROMPT : str = """
You are J.A.R.V.I.S., a sophisticated AI personal assistant — precise,
helpful, and occasionally witty like Tony Stark's AI.

You specialize in:
1. JAVA PROGRAMMING — OOP, design patterns, Spring Boot, Maven, concurrency,
   Streams API, JVM internals, debugging.
2. LINEAR ALGEBRA — Vectors, matrices, determinants, eigenvalues/eigenvectors,
   SVD, transformations. Always show step-by-step working.
3. WEB DEVELOPMENT — HTML/CSS/JS, React, Node.js, REST APIs, SQL & NoSQL,
   responsive design, web performance.

When the user requests a SYSTEM ACTION, reply ONLY with this exact JSON:
  {"action": "<action_name>", "target": "<value>"}

Valid actions:
  open_app, web_search, get_time, get_date, get_news,
  get_weather, wiki_search, play_music, take_screenshot

For all other queries, reply in plain conversational text (no JSON).
Keep answers concise (under 200 words) unless detail is requested.
When explaining code, always include a short working example.
"""


# ══════════════════════════════════════════════════════════════════
#  TERMINAL COLOURS
# ══════════════════════════════════════════════════════════════════
CY = "\033[96m"; GR = "\033[92m"; YL = "\033[93m"
RD = "\033[91m"; BD = "\033[1m";  DM = "\033[2m"; RS = "\033[0m"

def jprint(text: str):
    print(f"\n{CY}{BD}[JARVIS]{RS}")
    for line in textwrap.wrap(text, 70):
        print(f"  {line}")
    print()

def info(m): print(f"  {DM}[·] {m}{RS}")
def warn(m): print(f"  {YL}[!] {m}{RS}")
def err(m):  print(f"  {RD}[x] {m}{RS}")

def banner():
    print(f"""
{CY}{BD}
  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
  ░        J . A . R . V . I . S               ░
  ░     Just A Rather Very Intelligent System  ░
  ░         Voice + Text Hybrid Mode           ░
  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
{RS}
  {DM}Say "Jarvis" to use voice  |  Just type to use keyboard{RS}
  {DM}Type 'help' for commands   |  Type 'exit' to quit{RS}
  {DM}{'─'*46}{RS}
""")


# ══════════════════════════════════════════════════════════════════
#  VOICE ENGINE  (Text-to-Speech)
# ══════════════════════════════════════════════════════════════════
class VoiceEngine:
    def __init__(self):
        self._lock = threading.Lock()
        if not TTS_AVAILABLE:
            return
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate",   Config.VOICE_RATE)
            self.engine.setProperty("volume", Config.VOICE_VOLUME)
            voices = self.engine.getProperty("voices")
            if voices:
                for v in voices:
                    name = v.name.lower()
                    if any(x in name for x in ["david", "mark", "male", "george"]):
                        self.engine.setProperty("voice", v.id)
                        break
        except Exception as e:
            warn(f"TTS init failed: {e}")

    def speak(self, text: str):
        jprint(text)
        if not TTS_AVAILABLE:
            return
        with self._lock:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception:
                pass  # fall back to text-only silently


# ══════════════════════════════════════════════════════════════════
#  EARS  (Speech-to-Text — Windows tuned)
# ══════════════════════════════════════════════════════════════════
class Ears:
    def __init__(self):
        if not SR_AVAILABLE:
            return
        self.r = sr.Recognizer()
        self.r.energy_threshold         = Config.ENERGY_THRESHOLD
        self.r.dynamic_energy_threshold = Config.DYNAMIC_ENERGY
        self.r.pause_threshold          = Config.PAUSE_THRESHOLD
        self.r.operation_timeout        = None

    def calibrate(self):
        if not SR_AVAILABLE:
            return
        try:
            with sr.Microphone() as source:
                info(f"Calibrating mic for {Config.AMBIENT_CALIBRATION}s — stay quiet…")
                self.r.adjust_for_ambient_noise(source, duration=Config.AMBIENT_CALIBRATION)
                info(f"Mic ready. Energy threshold = {int(self.r.energy_threshold)}")
        except Exception as e:
            warn(f"Mic calibration failed: {e}. Typing mode still works fine.")

    def _recognize(self, audio) -> str | None:
        try:
            return self.r.recognize_google(audio).lower()
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            warn("Google STT offline. Check your internet.")
            return None

    def listen_for_wake_word(self, timeout: int = 2) -> bool:
        if not SR_AVAILABLE:
            return False
        try:
            with sr.Microphone() as source:
                audio = self.r.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=Config.PHRASE_LIMIT_WAKE
                )
            text = self._recognize(audio)
            if text:
                info(f"Heard: '{text}'")
            return bool(text and Config.WAKE_WORD in text)
        except sr.WaitTimeoutError:
            return False
        except Exception:
            return False

    def listen_for_command(self) -> str | None:
        if not SR_AVAILABLE:
            return None
        try:
            with sr.Microphone() as source:
                info("Listening for your command…")
                self.r.adjust_for_ambient_noise(source, duration=0.3)
                audio = self.r.listen(
                    source,
                    timeout=8,
                    phrase_time_limit=Config.PHRASE_LIMIT_COMMAND
                )
            result = self._recognize(audio)
            if result:
                print(f"\n  {GR}{BD}[YOU — voice]{RS} {result}")
            return result
        except sr.WaitTimeoutError:
            warn("No command heard. Type it instead.")
            return None
        except Exception as e:
            warn(f"Command listen error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════
#  BRAIN  (Gemini LLM)
# ══════════════════════════════════════════════════════════════════
class Brain:
    def __init__(self):
        if Config.GEMINI_API_KEY in ("PASTE_YOUR_NEW_API_KEY_HERE", ""):
            raise ValueError(
                f"\n  {RD}[x] Gemini API key not set!{RS}\n"
                "      Open jarvis.py → find Config.GEMINI_API_KEY\n"
                "      Paste your NEW key there and save.\n"
                "      Get a free key at: https://aistudio.google.com/app/apikey\n"
            )
        genai.configure(api_key=Config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",   # ← updated
    system_instruction=Config.SYSTEM_PROMPT
)
        self.chat = self.model.start_chat(history=[])

    def think(self, prompt: str) -> str:
        try:
            info("Thinking…")
            response = self.chat.send_message(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Neural link error: {e}"

    def reset(self):
        self.chat = self.model.start_chat(history=[])
        info("Memory cleared.")


# ══════════════════════════════════════════════════════════════════
#  SYSTEM INTEGRATION
# ══════════════════════════════════════════════════════════════════
class System:
    def _run(self, cmd):
        try:
            subprocess.Popen(
                cmd, shell=isinstance(cmd, str),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            err("App not found. Check Config.APP_PATHS.")

    def get_time(self) -> str:
        return datetime.datetime.now().strftime("The time is %I:%M %p.")

    def get_date(self) -> str:
        return datetime.datetime.now().strftime("Today is %A, %B %d, %Y.")

    def open_app(self, name: str) -> str:
        aliases = {
            "vs code": "vscode", "visual studio code": "vscode",
            "google chrome": "chrome", "browser": "chrome",
            "command prompt": "terminal", "cmd": "terminal",
            "music": "spotify",
        }
        key = aliases.get(name.lower(), name.lower().replace(" ", ""))
        path = Config.APP_PATHS.get(key, name)
        info(f"Launching {name}…")
        self._run(path)
        return f"Opening {name}."

    def web_search(self, query: str) -> str:
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        webbrowser.open(url)
        return f"Searching Google for: {query}"

    def get_news(self) -> str:
        try:
            resp = requests.get(
                "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
                timeout=7
            )
            soup = BeautifulSoup(resp.text, "xml")
            items = soup.find_all("item", limit=5)
            headlines = [i.find("title").text for i in items if i.find("title")]
            return "Top headlines:\n" + "\n".join(
                f"  {n+1}. {h}" for n, h in enumerate(headlines)
            )
        except Exception as e:
            return f"News unavailable: {e}"

    def get_weather(self, city: str = "Kerala") -> str:
        try:
            r = requests.get(f"https://wttr.in/{city}?format=3", timeout=7)
            return r.text.strip()
        except Exception:
            return "Weather service unreachable."

    def wiki_search(self, query: str) -> str:
        if not WIKI_OK:
            return "Run: pip install wikipedia"
        try:
            return wikipedia.summary(query, sentences=3, auto_suggest=True)
        except wikipedia.exceptions.DisambiguationError as e:
            return f"Ambiguous. Did you mean: {', '.join(e.options[:4])}?"
        except Exception as e:
            return f"Wikipedia error: {e}"

    def play_music(self, query: str = "") -> str:
        if query:
            webbrowser.open(
                f"https://music.youtube.com/search?q={requests.utils.quote(query)}"
            )
            return f"Opening YouTube Music for: {query}"
        self._run("spotify")
        return "Opening Spotify."

    def take_screenshot(self, fname: str = "") -> str:
        try:
            import pyautogui
            name = fname or f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            pyautogui.screenshot().save(name)
            return f"Screenshot saved as {name}"
        except ImportError:
            return "Run: pip install pyautogui Pillow"

    def execute(self, action: str, target: str) -> str:
        table = {
            "get_time"        : lambda: self.get_time(),
            "get_date"        : lambda: self.get_date(),
            "open_app"        : lambda: self.open_app(target),
            "web_search"      : lambda: self.web_search(target),
            "wiki_search"     : lambda: self.wiki_search(target),
            "get_news"        : lambda: self.get_news(),
            "get_weather"     : lambda: self.get_weather(target or "Kerala"),
            "take_screenshot" : lambda: self.take_screenshot(target),
            "play_music"      : lambda: self.play_music(target),
        }
        fn = table.get(action.lower())
        return fn() if fn else f"Unknown action: '{action}'"


# ══════════════════════════════════════════════════════════════════
#  RESPONSE PARSER
# ══════════════════════════════════════════════════════════════════
def parse(raw: str):
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            d = json.loads(cleaned)
            if "action" in d and "target" in d:
                return d, None
        except json.JSONDecodeError:
            pass
    return None, raw


# ══════════════════════════════════════════════════════════════════
#  KEYBOARD INPUT THREAD
#  Runs in background so typing works even while mic is listening
# ══════════════════════════════════════════════════════════════════
class KeyboardInput:
    def __init__(self):
        self.pending = None
        self._stop   = False
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while not self._stop:
            try:
                line = input(f"  {GR}{BD}TYPE >{RS} ").strip()
                if line:
                    self.pending = line
            except EOFError:
                break

    def get(self) -> str | None:
        val = self.pending
        self.pending = None
        return val

    def stop(self):
        self._stop = True


# ══════════════════════════════════════════════════════════════════
#  HELP
# ══════════════════════════════════════════════════════════════════
HELP = f"""
{CY}{BD}  Commands{RS}
  {DM}{'─'*44}{RS}
  {YL}System{RS}
    time / date             Current time or date
    weather [city]          Live weather
    news                    Top 5 headlines
    open [app]              Launch app (vscode, chrome, notepad…)
    search [query]          Google in browser
    screenshot              Save screenshot
    play [song/genre]       YouTube Music / Spotify

  {YL}Knowledge (powered by Gemini){RS}
    wiki [topic]            Wikipedia summary
    Any question            Java, Linear Algebra, Web Dev, anything

  {YL}Session{RS}
    reset / clear           Clear AI memory
    help                    Show this menu
    exit                    Quit JARVIS
  {DM}{'─'*44}{RS}
  {DM}  Voice: say "Jarvis" then speak your command{RS}
  {DM}  Text : just type below and press Enter{RS}
"""


# ══════════════════════════════════════════════════════════════════
#  SHORTCUTS  (fast path — no LLM needed)
# ══════════════════════════════════════════════════════════════════
def shortcut(cmd: str, sys_: System) -> str | None:
    lo = cmd.lower()
    if lo in ("time", "what time is it", "current time"):
        return sys_.get_time()
    if lo in ("date", "today's date", "what day is it", "what's the date"):
        return sys_.get_date()
    if lo in ("news", "headlines", "top news"):
        return sys_.get_news()
    if lo == "screenshot":
        return sys_.take_screenshot()
    m = re.match(r"weather(?:\s+(?:in\s+)?(.+))?", lo)
    if m:
        return sys_.get_weather((m.group(1) or "Kerala").strip())
    m = re.match(r"open\s+(.+)", lo)
    if m:
        return sys_.open_app(m.group(1).strip())
    m = re.match(r"(?:search|google)\s+(.+)", lo)
    if m:
        return sys_.web_search(m.group(1).strip())
    m = re.match(r"wiki(?:pedia)?\s+(.+)", lo)
    if m:
        return sys_.wiki_search(m.group(1).strip())
    m = re.match(r"play\s*(.*)", lo)
    if m:
        return sys_.play_music(m.group(1).strip())
    return None


# ══════════════════════════════════════════════════════════════════
#  PROCESS COMMAND  (shared by voice + text paths)
# ══════════════════════════════════════════════════════════════════
def process(cmd: str, brain: Brain, sys_: System, voice: VoiceEngine) -> bool:
    lo = cmd.lower()

    if lo in ("exit", "quit", "bye", "shutdown", "shut down", "goodbye"):
        voice.speak("All systems shutting down. Goodbye.")
        return False

    if lo == "help":
        print(HELP)
        return True

    if lo in ("reset", "clear", "reset memory", "clear memory"):
        brain.reset()
        voice.speak("Memory cleared. Fresh start.")
        return True

    result = shortcut(cmd, sys_)
    if result:
        voice.speak(result)
        return True

    # LLM fallback
    raw = brain.think(cmd)
    action_dict, plain = parse(raw)
    if action_dict:
        r = sys_.execute(action_dict["action"], action_dict["target"])
        voice.speak(r)
    else:
        voice.speak(plain or "No response received.")

    return True


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    banner()

    try:
        brain = Brain()
    except ValueError as e:
        print(e)
        sys.exit(1)

    voice = VoiceEngine()
    ears  = Ears()
    sys_  = System()
    kb    = KeyboardInput()

    if SR_AVAILABLE:
        ears.calibrate()

    h = datetime.datetime.now().hour
    greet = "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"
    voice.speak(
        f"{greet}. JARVIS online. "
        f"Say '{Config.WAKE_WORD}' to use your voice, "
        "or just type your command below."
    )

    running = True
    print(f"\n  {DM}Voice listening in background | Type anytime below{RS}\n")

    while running:

        # ── Keyboard (checked every loop — instant response) ──────
        typed = kb.get()
        if typed:
            print(f"\n  {GR}{BD}[YOU — typed]{RS} {typed}")
            running = process(typed, brain, sys_, voice)
            print(f"\n  {DM}Voice listening in background | Type anytime below{RS}\n")
            continue

        # ── Voice (2s timeout so keyboard stays responsive) ───────
        if SR_AVAILABLE:
            woke = ears.listen_for_wake_word(timeout=2)
            if woke:
                voice.speak("Yes? I'm listening.")
                cmd = ears.listen_for_command()
                if cmd:
                    running = process(cmd, brain, sys_, voice)
                    print(f"\n  {DM}Voice listening in background | Type anytime below{RS}\n")
                else:
                    voice.speak("Couldn't catch that — try typing it instead.")
        else:
            time.sleep(0.1)

    kb.stop()
    print(f"\n  {DM}JARVIS offline.{RS}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {DM}Interrupted. Goodbye.{RS}\n")