import asyncio
import logging
from typing import Any

from fastapi_cache import FastAPICache

logger = logging.getLogger(__name__)


class ResultNotFound(KeyError):
    pass


class CommandManager:
    command_cache_prefix: str = 'command_result'
    command_cache_timeout: int = 60 * 60 * 24

    def __init__(self, cache_prefix: str = None, *args, **kwargs):
        if cache_prefix is not None:
            self.command_cache_prefix: str = cache_prefix

    def _get_command_key(self, request_id: str):
        return f"{self.command_cache_prefix}:{request_id}"

    async def set_result(self, request_id: str, result: Any):
        cache = FastAPICache.get_backend()
        await cache.set(self._get_command_key(request_id), result, self.command_cache_timeout)

    async def get_result_nowait(self, request_id: str):
        cache = FastAPICache.get_backend()
        cache_key = self._get_command_key(request_id)
        result = await cache.get(cache_key)
        if result is not None:
            await cache.clear(cache_key)
            return result
        return result

    async def get_result(self, request_id: str, interval: float = 1, timeout: int = 30) -> Any:
        assert timeout > 0
        assert interval > 0
        waited = 0
        while waited < timeout:
            result = await self.get_result_nowait(request_id)
            if result is not None:
                logger.debug(f'Get result ok request_id:{request_id}, taken time:{waited}')
                return result
            await asyncio.sleep(interval)
            waited += interval
        raise asyncio.TimeoutError(
            f'Wait result timeout, request_id:{request_id}, wait more than {timeout:.1f} seconds')


command_manager = CommandManager()
