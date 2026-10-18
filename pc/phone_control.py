"""Versioned, bounded USB control messages; independent of GUI dependencies."""
import json
import re
import struct

ADDRESS = re.compile(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}\Z")
COMMANDS = {name: index for index, name in enumerate(
    ("status", "pair", "cancel", "approve", "reject", "select", "disconnect", "forget"), 1)}


def command_frame(command):
    from listen import CONTROL_MAGIC, checksum
    address = command.get("address", "")
    if address and not ADDRESS.fullmatch(address):
        raise ValueError("Invalid Bluetooth address")
    payload = struct.pack("<BB6sI", COMMANDS[command["cmd"]], bool(command.get("force")),
                          bytes.fromhex(address.replace(":", "")) if address else bytes(6),
                          command.get("challenge", 0))
    fields = struct.pack("<HHI", len(payload), 0, 0)
    return CONTROL_MAGIC + fields + struct.pack("<I", checksum(fields + payload)) + payload


def decode_status(payload):
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get("v") != 1:
            return None
        if not isinstance(value.get("phones"), list) or len(value["phones"]) > 6:
            return None
        for phone in value["phones"]:
            if not isinstance(phone, dict) or not ADDRESS.fullmatch(phone.get("address", "")):
                return None
            if not isinstance(phone.get("name"), str):
                return None
        if value.get("selected") != "" and not ADDRESS.fullmatch(value.get("selected", "")):
            return None
        if type(value.get("pairing")) is not int or not 0 <= value["pairing"] <= 60:
            return None
        if any(type(value.get(key)) is not bool for key in ("ready", "hfp", "a2dp", "call")):
            return None
        if not isinstance(value.get("message"), str):
            return None
        pending = value.get("pending")
        if pending is not None:
            if not isinstance(pending, dict) or not ADDRESS.fullmatch(pending.get("address", "")):
                return None
            if type(pending.get("number")) is not int or not 0 <= pending["number"] <= 999999:
                return None
            if type(pending.get("challenge")) is not int or not 0 <= pending["challenge"] <= 0xFFFFFFFF:
                return None
            if type(pending.get("confirmed")) is not bool:
                return None
        return value
    except (ValueError, TypeError, UnicodeError):
        return None
