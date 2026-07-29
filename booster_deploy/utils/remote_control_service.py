from __future__ import annotations

import atexit
import select
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass

import evdev


@dataclass
class JoystickConfig:
    custom_mode_button: int = evdev.ecodes.BTN_A
    policy_start_button: int = evdev.ecodes.BTN_B
    squat_toggle_button: int = evdev.ecodes.BTN_B


class RemoteControlService:
    """Read the small set of operator controls used by the squat task."""

    def __init__(self, config: JoystickConfig | None = None):
        self.config = config or JoystickConfig()
        self._lock = threading.Lock()
        self._running = True
        self._custom_mode_requested = False
        self._policy_start_requested = False
        self._squat_enabled = False
        self._toggle_armed = False
        self._suppress_toggle_until_release = False
        self._stdin_tty = False
        self._old_termios = None
        self.keyboard_runner = None
        self.joystick_runner = None

        try:
            self._init_joystick()
            self._start_joystick_thread()
        except Exception as exc:
            print(f"{exc}; using keyboard control")
            self.joystick = None
            self._start_keyboard_thread()
        atexit.register(self.close)

    def get_operation_hint(self) -> str:
        if self.joystick is not None:
            return "Press joystick B to toggle squat on/off."
        return "Press keyboard 's' to toggle squat on/off."

    def get_custom_mode_operation_hint(self) -> str:
        if self.joystick is not None:
            return "Press joystick A to enter custom mode."
        return "Press keyboard 'x' to enter custom mode."

    def get_policy_start_operation_hint(self) -> str:
        if self.joystick is not None:
            return "Press joystick B to start the squat policy."
        return "Press keyboard 'r' to start the squat policy."

    # Compatibility with the existing portal name.
    get_rl_gait_operation_hint = get_policy_start_operation_hint

    def print_controls(self, *, real_robot: bool) -> None:
        """Print the controls available for the selected input device."""
        if self.joystick is not None:
            if real_robot:
                controls = (
                    "  A  Enter custom mode",
                    "  B  Start policy; then toggle squat on/off",
                )
            else:
                controls = ("  B  Toggle squat on/off",)
        elif real_robot:
            controls = (
                "  x  Enter custom mode",
                "  r  Start policy",
                "  s  Toggle squat on/off after policy startup",
            )
        else:
            controls = ("  s  Toggle squat on/off",)

        print("\nControls:")
        print("\n".join(controls))
        print("  Ctrl-C  Stop\n")

    def start_custom_mode(self) -> bool:
        with self._lock:
            return self._custom_mode_requested

    def start_rl_gait(self) -> bool:
        with self._lock:
            return self._policy_start_requested

    def arm_squat_toggle(self) -> None:
        """Enable toggle handling without reusing the policy-start press."""
        with self._lock:
            self._toggle_armed = True
            if self.joystick is not None:
                self._suppress_toggle_until_release = (
                    self.config.squat_toggle_button in self.joystick.active_keys()
                )

    def get_squat_enabled(self) -> bool:
        with self._lock:
            return self._squat_enabled

    def _toggle_squat(self) -> None:
        with self._lock:
            if not self._toggle_armed:
                return
            self._squat_enabled = not self._squat_enabled
            state = "enabled" if self._squat_enabled else "disabled"
        print(f"Squat {state}")

    def _handle_keyboard_press(self, key: str) -> None:
        with self._lock:
            if key == "x":
                self._custom_mode_requested = True
            elif key == "r":
                self._policy_start_requested = True
        if key == "s":
            self._toggle_squat()

    def _init_joystick(self) -> None:
        devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        self.joystick = next(
            (
                device
                for device in devices
                if evdev.ecodes.EV_KEY in device.capabilities()
                and self.config.custom_mode_button
                in dict(device.capabilities()).get(evdev.ecodes.EV_KEY, [])
            ),
            None,
        )
        if self.joystick is None:
            raise RuntimeError("No suitable joystick found")
        print(f"Selected joystick: {self.joystick.name}")

    def _start_joystick_thread(self) -> None:
        self.joystick_runner = threading.Thread(
            target=self._run_joystick, daemon=True, name="squat-joystick"
        )
        self.joystick_runner.start()

    def _run_joystick(self) -> None:
        while self._running:
            try:
                event = self.joystick.read_one()
                if event is None:
                    time.sleep(0.01)
                    continue
                if event.type != evdev.ecodes.EV_KEY:
                    continue

                if event.code == self.config.custom_mode_button and event.value == 1:
                    with self._lock:
                        self._custom_mode_requested = True
                if event.code == self.config.policy_start_button and event.value == 1:
                    with self._lock:
                        if not self._toggle_armed:
                            self._policy_start_requested = True
                if event.code == self.config.squat_toggle_button:
                    if event.value == 0:
                        with self._lock:
                            self._suppress_toggle_until_release = False
                    elif event.value == 1:
                        with self._lock:
                            suppressed = self._suppress_toggle_until_release
                        if not suppressed:
                            self._toggle_squat()
            except Exception as exc:
                if self._running:
                    print(f"Joystick input error: {exc}")
                    time.sleep(0.05)

    def _start_keyboard_thread(self) -> None:
        try:
            self._stdin_tty = sys.stdin.isatty()
            if self._stdin_tty:
                self._old_termios = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            self._stdin_tty = False
        self.keyboard_runner = threading.Thread(
            target=self._keyboard_listener, daemon=True, name="squat-keyboard"
        )
        self.keyboard_runner.start()

    def _keyboard_listener(self) -> None:
        if not self._stdin_tty:
            return
        fd = sys.stdin.fileno()
        try:
            tty.setcbreak(fd)
            while self._running:
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable:
                    key = sys.stdin.read(1).lower()
                    if key != "\x03":
                        self._handle_keyboard_press(key)
        finally:
            if self._old_termios is not None:
                termios.tcsetattr(fd, termios.TCSADRAIN, self._old_termios)

    def close(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stdin_tty and self._old_termios is not None:
            try:
                termios.tcsetattr(
                    sys.stdin.fileno(), termios.TCSADRAIN, self._old_termios
                )
            except Exception:
                pass
        if self.joystick is not None:
            try:
                self.joystick.close()
            except Exception:
                pass
        for runner in (self.joystick_runner, self.keyboard_runner):
            if runner is not None and runner is not threading.current_thread():
                runner.join(timeout=1.0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
