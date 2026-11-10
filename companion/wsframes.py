"""Minimal WebSocket frames for one localhost client."""

import base64
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept_key(key):
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_text(text):
    payload = text.encode("utf-8")
    length = len(payload)
    header = bytearray([0x81])
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + payload


def encode_close():
    return bytes([0x88, 0x00])


def encode_client_text(text):
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x81])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + masked


def _unmask(payload, mask):
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


class FrameParser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while True:
            frame = self._pop()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _pop(self):
        if len(self.buffer) < 2:
            return None
        first, second = self.buffer[0], self.buffer[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(self.buffer) < 4:
                return None
            length = struct.unpack("!H", self.buffer[2:4])[0]
            offset = 4
        elif length == 127:
            if len(self.buffer) < 10:
                return None
            length = struct.unpack("!Q", self.buffer[2:10])[0]
            offset = 10
        mask_len = 4 if masked else 0
        total = offset + mask_len + length
        if len(self.buffer) < total:
            return None
        mask = self.buffer[offset:offset + mask_len] if masked else b""
        start = offset + mask_len
        payload = bytes(self.buffer[start:start + length])
        del self.buffer[:total]
        if masked:
            payload = _unmask(payload, mask)
        return opcode, payload
