"""音频设备枚举（供 UI 设置面板与采集器选择设备）。

soundcard 按设备对象采集而非索引，因此同时返回展示信息与原始对象。
WASAPI 环回采集源是 all_microphones(include_loopback=True) 中 isloopback=True 的
_Microphone 对象；all_speakers() 返回的是 _Speaker，只能播放不能录音。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceInfo:
    name: str
    kind: str            # "mic" | "speaker"
    obj: Any = field(repr=False, default=None)   # soundcard 设备对象

    @property
    def label(self) -> str:
        return self.name or f"未命名{self.kind}"


@dataclass
class AudioDevices:
    mics: list[DeviceInfo] = field(default_factory=list)
    speakers: list[DeviceInfo] = field(default_factory=list)

    def get_mic(self, name: str | None) -> Any | None:
        if not name:
            return self.mics[0].obj if self.mics else None
        for d in self.mics:
            if d.name == name:
                return d.obj
        return self.mics[0].obj if self.mics else None

    def get_speaker(self, name: str | None) -> Any | None:
        if not name:
            return self.speakers[0].obj if self.speakers else None
        for d in self.speakers:
            if d.name == name:
                return d.obj
        return self.speakers[0].obj if self.speakers else None


def list_audio_devices() -> AudioDevices:
    """枚举设备。失败时返回空 AudioDevices，不抛异常。"""
    result = AudioDevices()
    try:
        import soundcard as sc
    except ImportError:
        return result

    try:
        for m in sc.all_microphones(include_loopback=True):
            if getattr(m, "isloopback", False):
                continue
            result.mics.append(DeviceInfo(name=m.name, kind="mic", obj=m))
    except Exception:
        pass

    try:
        # 环回源本质是 isloopback=True 的 _Microphone（不是 _Speaker）
        for s in sc.all_microphones(include_loopback=True):
            if getattr(s, "isloopback", False):
                result.speakers.append(DeviceInfo(name=s.name, kind="speaker", obj=s))
    except Exception:
        pass

    return result
