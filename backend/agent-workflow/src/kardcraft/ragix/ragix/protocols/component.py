# protocols/component.py - 基础组件协议
"""
基础组件协议定义

参考 Yuxi-Know 的 ABC 设计模式，定义所有组件的基础接口
"""

from typing import Protocol, runtime_checkable, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ComponentConfig:
    """组件配置基类 - 参考 Yuxi-Know 配置模式"""
    name: str
    enabled: bool = True
    priority: int = 100
    params: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.params is None:
            self.params = {}


@runtime_checkable
class Component(Protocol):
    """组件基协议 - 所有组件实现此协议"""
    
    def get_name(self) -> str:
        """获取组件名称"""
        ...
    
    def get_config(self) -> ComponentConfig:
        """获取组件配置"""
        ...
    
    async def initialize(self) -> bool:
        """初始化组件"""
        ...
    
    async def shutdown(self) -> None:
        """关闭组件"""
        ...


class BaseComponent(ABC):
    """组件基类 - 提供通用实现"""
    
    def __init__(self, config: ComponentConfig):
        self.config = config
        self._initialized = False
    
    def get_name(self) -> str:
        return self.config.name
    
    def get_config(self) -> ComponentConfig:
        return self.config
    
    async def initialize(self) -> bool:
        """初始化组件 - 子类可重写"""
        if self._initialized:
            return True
        
        success = await self._do_initialize()
        self._initialized = success
        return success
    
    async def shutdown(self) -> None:
        """关闭组件 - 子类可重写"""
        if not self._initialized:
            return
        
        await self._do_shutdown()
        self._initialized = False
    
    @abstractmethod
    async def _do_initialize(self) -> bool:
        """具体初始化逻辑 - 子类必须实现"""
        pass
    
    async def _do_shutdown(self) -> None:
        """具体关闭逻辑 - 子类可重写"""
        pass
    
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized


@dataclass
class HealthStatus:
    """健康状态 - 参考 Yuxi-Know 健康检查"""
    status: str  # "healthy", "unhealthy", "unavailable", "error"
    message: str
    details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}
    
    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"


@runtime_checkable
class HealthCheckable(Protocol):
    """健康检查协议"""
    
    async def check_health(self) -> HealthStatus:
        """检查组件健康状态"""
        ...