"""maibot_sdk 离线桩：让 plugin.py 在未安装 SDK 的环境可导入并自检组件声明。

仅覆盖本插件用到的 API 面；行为与真实 SDK 不保证一致，只用于结构自检。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import pydantic

CONFIG_RELOAD_SCOPE_SELF = "self"


class PluginConfigBase(pydantic.BaseModel):
    """真实 SDK 中为带 __ui_* 元数据处理与归一化逻辑的 BaseModel 子类。"""


Field = pydantic.Field


def _component_decorator(kind: str, name: str, **meta: Any):
    def decorator(fn):
        fn.__maibot_component_info__ = {"kind": kind, "name": name, **meta}
        return fn

    return decorator


def Command(name: str, description: str = "", pattern: str = "", aliases=None, **meta):
    return _component_decorator(
        "command", name, description=description, pattern=pattern, aliases=aliases, **meta
    )


def Tool(name: str, description: str = "", brief_description: str = "",
         detailed_description: str = "", parameters=None, **meta):
    return _component_decorator(
        "tool", name, description=description, brief_description=brief_description,
        detailed_description=detailed_description, parameters=parameters, **meta
    )


class ToolParamType:
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameterInfo:
    name: str
    param_type: str = ToolParamType.STRING
    description: str = ""
    required: bool = True
    enum_values: list | None = None
    items_schema: dict | None = None
    default: Any = None


class MaiBotPlugin:
    """真实 SDK 中由 Runner 注入 ctx；此处仅实现 get_components 的扫描逻辑。"""

    config_model: ClassVar = None
    ctx: Any = None

    async def on_load(self) -> None:
        raise NotImplementedError

    async def on_unload(self) -> None:
        raise NotImplementedError

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        raise NotImplementedError

    def get_components(self) -> list[dict]:
        comps = []
        for klass in type(self).__mro__:
            for value in vars(klass).values():
                info = getattr(value, "__maibot_component_info__", None)
                if info:
                    comps.append(dict(info))
        return comps
