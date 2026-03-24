"""
健康检查工具

提供各个服务的健康检查功能。
"""

import asyncio
import logging
from typing import Dict, Any
from dataclasses import dataclass
from datetime import datetime

from .file_storage_client import check_file_storage_health
from ..sandbox_broker.container_runtime import check_sandbox_runtime_ready

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """健康状态"""
    service: str
    healthy: bool
    response_time_ms: float
    error: str = ""
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class HealthChecker:
    """健康检查器"""
    
    def __init__(self):
        self.services = {
            "file-storage": check_file_storage_health,
            "sandbox-runtime": self._check_sandbox_runtime_health,
        }

    async def _check_sandbox_runtime_health(self) -> bool:
        healthy, reason = check_sandbox_runtime_ready()
        if not healthy:
            raise RuntimeError(reason)
        return healthy
    
    async def check_service(self, service_name: str) -> HealthStatus:
        """检查单个服务健康状态"""
        if service_name not in self.services:
            return HealthStatus(
                service=service_name,
                healthy=False,
                response_time_ms=0,
                error=f"Unknown service: {service_name}"
            )
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            check_func = self.services[service_name]
            healthy = await asyncio.wait_for(check_func(), timeout=10.0)
            
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            
            return HealthStatus(
                service=service_name,
                healthy=healthy,
                response_time_ms=response_time
            )
            
        except asyncio.TimeoutError:
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            return HealthStatus(
                service=service_name,
                healthy=False,
                response_time_ms=response_time,
                error="Health check timeout"
            )
        except Exception as e:
            response_time = (asyncio.get_event_loop().time() - start_time) * 1000
            return HealthStatus(
                service=service_name,
                healthy=False,
                response_time_ms=response_time,
                error=str(e)
            )
    
    async def check_all_services(self) -> Dict[str, HealthStatus]:
        """检查所有服务健康状态"""
        tasks = []
        for service_name in self.services.keys():
            task = asyncio.create_task(self.check_service(service_name))
            tasks.append((service_name, task))
        
        results = {}
        for service_name, task in tasks:
            try:
                status = await task
                results[service_name] = status
            except Exception as e:
                results[service_name] = HealthStatus(
                    service=service_name,
                    healthy=False,
                    response_time_ms=0,
                    error=f"Health check failed: {e}"
                )
        
        return results
    
    async def get_overall_health(self) -> Dict[str, Any]:
        """获取整体健康状态"""
        service_statuses = await self.check_all_services()
        
        all_healthy = all(status.healthy for status in service_statuses.values())
        total_services = len(service_statuses)
        healthy_services = sum(1 for status in service_statuses.values() if status.healthy)
        
        return {
            "healthy": all_healthy,
            "status": "healthy" if all_healthy else "degraded",
            "services": {
                name: {
                    "healthy": status.healthy,
                    "response_time_ms": status.response_time_ms,
                    "error": status.error,
                    "timestamp": status.timestamp.isoformat()
                }
                for name, status in service_statuses.items()
            },
            "summary": {
                "total_services": total_services,
                "healthy_services": healthy_services,
                "unhealthy_services": total_services - healthy_services
            },
            "timestamp": datetime.now().isoformat()
        }


# 全局健康检查器实例
_health_checker: HealthChecker = None


def get_health_checker() -> HealthChecker:
    """获取健康检查器实例"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


# 便捷函数
async def check_service_health(service_name: str) -> HealthStatus:
    """便捷函数：检查单个服务健康状态"""
    checker = get_health_checker()
    return await checker.check_service(service_name)


async def check_all_services_health() -> Dict[str, HealthStatus]:
    """便捷函数：检查所有服务健康状态"""
    checker = get_health_checker()
    return await checker.check_all_services()


async def get_overall_health_status() -> Dict[str, Any]:
    """便捷函数：获取整体健康状态"""
    checker = get_health_checker()
    return await checker.get_overall_health()
