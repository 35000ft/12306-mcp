import os
from typing import Any, Optional

from dify_client import AsyncClient, models
from dify_client.models import WorkflowsRunResponse
from loguru import logger


class DifyAIClient:
    def __init__(self, app_name: str = None, api_base: Optional[str] = "https://api.dify.ai/v1"):
        self.api_base = api_base or os.getenv("DIFY_API_KEY", "https://api.dify.ai/v1")
        self.app_name = app_name
        if api_key := os.getenv(f"{app_name}_APIKEY"):
            self.api_key = api_key
        else:
            raise ValueError(f"API key not set, app:{app_name}")
        self.client = AsyncClient(api_key=self.api_key, api_base=self.api_base)

    async def run_workflow(self, inputs: dict[str, Any], timeout: float = 300.0) -> WorkflowsRunResponse:
        logger.info(f"Running Dify workflow, app_name:{self.app_name}")
        try:
            req = models.WorkflowsRunRequest(
                inputs=inputs,
                response_mode=models.ResponseMode.BLOCKING,
                user="nmtr-mcp",
            )
            response = await self.client.arun_workflows(req, timeout=timeout)
            return response
        except Exception as e:
            logger.exception(f"Dify workflow error: {e}", exc_info=e)
            raise
