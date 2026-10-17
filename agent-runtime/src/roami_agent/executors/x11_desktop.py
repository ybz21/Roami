"""Linux X11 observation and bounded XTEST input on an explicitly selected display."""

import hashlib
import io
import os
import socket
import struct
from pathlib import Path

from PIL import Image
from Xlib import XK, X, display
from Xlib.error import ConnectionClosedError, DisplayConnectionError, XError
from Xlib.ext import xtest
from Xlib.protocol import rq

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded


class XkbUseExtension(rq.ReplyRequest):
    _request = rq.Struct(
        rq.Card8("opcode"), rq.Opcode(0), rq.RequestLength(), rq.Card16("major"), rq.Card16("minor")
    )
    _reply = rq.Struct(
        rq.ReplyCode(),
        rq.Bool("supported"),
        rq.Card16("sequence_number"),
        rq.ReplyLength(),
        rq.Card16("major"),
        rq.Card16("minor"),
        rq.Pad(20),
    )


class XkbState(rq.ReplyRequest):
    _request = rq.Struct(
        rq.Card8("opcode"), rq.Opcode(4), rq.RequestLength(), rq.Card16("device"), rq.Pad(2)
    )
    _reply = rq.Struct(
        rq.ReplyCode(),
        rq.Card8("device"),
        rq.Card16("sequence_number"),
        rq.ReplyLength(),
        rq.Card8("mods"),
        rq.Card8("base_mods"),
        rq.Card8("latched_mods"),
        rq.Card8("locked_mods"),
        rq.Card8("group"),
        rq.Card8("locked_group"),
        rq.Int16("base_group"),
        rq.Int16("latched_group"),
        rq.Pad(14),
    )


class X11Desktop:
    failure_types = (OSError, ConnectionClosedError, DisplayConnectionError, XError)

    def __init__(self, display_name, *, image_side=1280):
        self.connection = None
        try:
            self._initialize(display_name, image_side)
        except BaseException:
            if self.connection:
                self.connection.close()
            raise

    def _initialize(self, display_name, image_side):
        self.connection = display.Display(display_name)
        self.errors = []
        self.connection.set_error_handler(lambda error, request: self.errors.append(error))
        self.screen = self.connection.screen()
        self.root = self.screen.root
        self.image_side = image_side
        if not self.connection.has_extension("XTEST"):
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503)
        extension = self.connection.query_extension("XKEYBOARD")
        if (
            not extension.present
            or not XkbUseExtension(
                display=self.connection.display, opcode=extension.major_opcode, major=1, minor=0
            ).supported
        ):
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503)
        self.keyboard_opcode = extension.major_opcode
        with socket.socket(fileno=os.dup(self.connection.fileno())) as peer:
            pid, uid, _ = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        process = Path("/proc") / str(pid) / "stat"
        process_stat = process.read_text()
        if process_stat.split("(", 1)[1].rsplit(")", 1)[0].casefold() == "xwayland":
            raise DomainError("DESKTOP_DRIVER_UNAVAILABLE", 503)
        start = process_stat.rsplit(")", 1)[1].split()[19]
        self.driver_id = hashlib.sha256(
            encoded(
                [
                    Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    pid,
                    start,
                    uid,
                    display_name,
                    self.root.id,
                ]
            ).encode()
        ).hexdigest()
        self._format()

    def _format(self):
        formats = self.connection.display.info.pixmap_formats
        visual = next(
            (
                visual
                for depth in self.screen.allowed_depths
                for visual in depth.visuals
                if visual.visual_id == self.screen.root_visual
            ),
            None,
        )
        if (
            self.connection.display.info.image_byte_order != X.LSBFirst
            or not any(
                item.depth == self.screen.root_depth
                and item.bits_per_pixel == 32
                and item.scanline_pad == 32
                for item in formats
            )
            or not visual
            or (visual.red_mask, visual.green_mask, visual.blue_mask) != (0xFF0000, 0xFF00, 0xFF)
        ):
            raise DomainError("DESKTOP_PIXEL_FORMAT_UNSUPPORTED", 503)

    def _metadata(self):
        geometry = self.root.get_geometry()
        if not 1 <= geometry.width * geometry.height <= 16_000_000:
            raise DomainError("DESKTOP_SCREEN_LIMIT", 503)
        pointer = self.root.query_pointer()
        focus = self.connection.get_input_focus().focus
        window = None
        if hasattr(focus, "get_geometry"):
            top = focus
            for _ in range(32):
                parent = top.query_tree().parent
                if parent.id == self.root.id or top.id == self.root.id:
                    break
                top = parent
            else:
                raise DomainError("DESKTOP_WINDOW_DEPTH_LIMIT", 503)
            bounds = top.get_geometry()
            translated = self.root.translate_coords(top, 0, 0)
            window = {
                "id": focus.id,
                "windowId": top.id,
                "x": translated.x,
                "y": translated.y,
                "width": bounds.width,
                "height": bounds.height,
            }
        keys = self.connection.query_keymap()
        minimum = self.connection.display.info.min_keycode
        mapping = self.connection.get_keyboard_mapping(
            minimum, self.connection.display.info.max_keycode - minimum + 1
        )
        self.keymap = {}
        for offset, symbols in enumerate(mapping):
            for index, symbol in enumerate(symbols):
                if symbol and index in {0, 1}:
                    self.keymap.setdefault(symbol, []).append((minimum + offset, index))
        keyboard = XkbState(
            display=self.connection.display, opcode=self.keyboard_opcode, device=0x100
        )
        return {
            "driverId": self.driver_id,
            "screen": {"width": geometry.width, "height": geometry.height},
            "pointer": {"x": pointer.root_x, "y": pointer.root_y, "mask": pointer.mask},
            "focus": window,
            "keyboardGroup": keyboard.group,
            "keyboardMods": keyboard.mods,
            "keysHeld": any(keys),
            "keyboardMapHash": hashlib.sha256(
                encoded([list(symbols) for symbols in mapping]).encode()
            ).hexdigest(),
        }

    def observe(self, *, focus_only=False):
        before = self._metadata()
        width, height = before["screen"]["width"], before["screen"]["height"]
        raw = self.root.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)
        image = Image.frombytes("RGB", (width, height), raw.data, "raw", "BGRX", 0, 1)
        region = {"x": 0, "y": 0, "width": width, "height": height}
        if focus_only:
            focus = before["focus"]
            if not focus or focus["windowId"] == self.root.id:
                raise DomainError("DESKTOP_FOCUS_REQUIRED", 409)
            left, top = max(0, focus["x"]), max(0, focus["y"])
            right = min(width, focus["x"] + focus["width"])
            bottom = min(height, focus["y"] + focus["height"])
            if right <= left or bottom <= top:
                raise DomainError("DESKTOP_SCENE_CHANGED", 409)
            image = image.crop((left, top, right, bottom))
            region = {"x": left, "y": top, "width": right - left, "height": bottom - top}
        signature = hashlib.sha256(encoded([before, region]).encode() + image.tobytes()).hexdigest()
        after = self._metadata()
        if before != after:
            raise DomainError("DESKTOP_SCENE_CHANGED", 409)
        image.thumbnail((self.image_side, self.image_side), Image.Resampling.LANCZOS)
        while True:
            output = io.BytesIO()
            image.save(output, format="PNG")
            body = output.getvalue()
            if len(body) <= 2 * 1024 * 1024:
                break
            if min(image.size) < 128:
                raise DomainError("DESKTOP_SCREEN_LIMIT", 503)
            image = image.resize(
                (max(1, image.width // 2), max(1, image.height // 2)), Image.Resampling.LANCZOS
            )
        self.connection.sync()
        if self.errors:
            self.errors.clear()
            raise DomainError("DESKTOP_SCENE_CHANGED", 409)
        return {
            **after,
            "signature": signature,
            "capturedMs": now_ms(),
            "coordinateSpace": "image_pixels",
            "captureMode": "focus" if focus_only else "screen",
            "captureRegion": region,
            "screenshot": {
                "width": image.width,
                "height": image.height,
                "scaleX": region["width"] / image.width,
                "scaleY": region["height"] / image.height,
                "originX": region["x"],
                "originY": region["y"],
            },
            "textInput": "ascii-group-0" if after["keyboardGroup"] == 0 else "unavailable",
        }, body

    def _key(self, name):
        symbol = XK.string_to_keysym(name) if len(name) != 1 else ord(name)
        choices = [(code, index) for code, index in self.keymap.get(symbol, []) if index in {0, 1}]
        if not symbol or not choices:
            raise DomainError("DESKTOP_KEY_UNSUPPORTED", 409)
        return min(choices, key=lambda item: (item[1], item[0]))

    def act(self, action, signature, cancelled):
        try:
            observed, _ = self.observe(focus_only=action.get("focusOnly", False))
        except self.failure_types:
            raise DomainError("DESKTOP_SCENE_CHANGED", 409) from None
        if observed["signature"] != signature:
            raise DomainError("DESKTOP_SCENE_CHANGED", 409)
        if cancelled.is_set():
            return {"state": "cancelled", "inputStopped": True, "outcomeKnown": True}
        if observed["keysHeld"] or observed["pointer"]["mask"] & (
            X.Button1Mask
            | X.Button2Mask
            | X.Button3Mask
            | X.ShiftMask
            | X.ControlMask
            | X.Mod1Mask
            | X.Mod4Mask
        ):
            raise DomainError("DESKTOP_INPUT_BUSY", 409)
        kind = action["kind"]
        key_plan = []
        if kind in {"key", "type"}:
            if observed["keyboardGroup"] != 0 or not observed["focus"]:
                raise DomainError("DESKTOP_KEYBOARD_UNAVAILABLE", 409)
            if kind == "type":
                if any(not 32 <= ord(char) <= 126 for char in action["text"]):
                    raise DomainError("DESKTOP_TEXT_UNSUPPORTED", 409)
                for char in action["text"]:
                    code, shift = self._key(char)
                    if char.isalpha() and observed["keyboardMods"] & X.LockMask:
                        shift = not shift
                    key_plan.append(([self._key("Shift_L")[0]] if shift else [], code))
            else:
                modifiers = {
                    "Ctrl": "Control_L",
                    "Alt": "Alt_L",
                    "Shift": "Shift_L",
                    "Super": "Super_L",
                }
                parts = action["key"].split("+")
                if len(parts) > 4 or any(part not in modifiers for part in parts[:-1]):
                    raise DomainError("DESKTOP_KEY_UNSUPPORTED", 409)
                key = (
                    parts[-1].lower()
                    if len(parts) > 1 and len(parts[-1]) == 1 and parts[-1].isalpha()
                    else parts[-1]
                )
                code, shift = self._key(key)
                modifier_names = [modifiers[name] for name in parts[:-1]]
                if shift and "Shift_L" not in modifier_names:
                    modifier_names.append("Shift_L")
                key_plan.append(([self._key(name)[0] for name in modifier_names], code))
        pressed_keys, pressed_buttons, sent = set(), set(), False
        try:
            if cancelled.is_set():
                return {"state": "cancelled", "inputStopped": True, "outcomeKnown": True}
            if kind in {"click", "scroll"}:
                transform = action["transform"]
                x = min(
                    observed["screen"]["width"] - 1,
                    transform["originX"] + int(action["x"] * transform["scaleX"]),
                )
                y = min(
                    observed["screen"]["height"] - 1,
                    transform["originY"] + int(action["y"] * transform["scaleY"]),
                )
                sent = True
                xtest.fake_input(self.connection, X.MotionNotify, x=x, y=y)
                buttons = (
                    [action.get("button", 1)]
                    if kind == "click"
                    else [4 if action["amount"] < 0 else 5] * abs(action["amount"])
                )
                for button in buttons:
                    if cancelled.is_set():
                        break
                    pressed_buttons.add(button)
                    xtest.fake_input(self.connection, X.ButtonPress, button)
                    xtest.fake_input(self.connection, X.ButtonRelease, button)
                    pressed_buttons.discard(button)
            else:
                for modifiers, code in key_plan:
                    if cancelled.is_set():
                        break
                    sent = True
                    for modifier in modifiers:
                        pressed_keys.add(modifier)
                        xtest.fake_input(self.connection, X.KeyPress, modifier)
                    pressed_keys.add(code)
                    xtest.fake_input(self.connection, X.KeyPress, code)
                    xtest.fake_input(self.connection, X.KeyRelease, code)
                    pressed_keys.discard(code)
                    for modifier in reversed(modifiers):
                        xtest.fake_input(self.connection, X.KeyRelease, modifier)
                        pressed_keys.discard(modifier)
            self.connection.sync()
            if self.errors:
                self.errors.clear()
                return {"state": "unknown", "inputStopped": False, "outcomeKnown": False}
            return {
                "state": "succeeded" if not cancelled.is_set() else "cancelled",
                "inputStopped": True,
                "outcomeKnown": True,
                "inputSent": sent,
            }
        finally:
            for key in pressed_keys:
                xtest.fake_input(self.connection, X.KeyRelease, key)
            for button in pressed_buttons:
                xtest.fake_input(self.connection, X.ButtonRelease, button)
            if pressed_keys or pressed_buttons:
                self.connection.sync()

    def close(self):
        self.connection.close()
