"""
Error handling framework for LangGraph nodes.
Implements retry, fallback, and error classification strategies.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Callable, List
from functools import wraps
from enum import Enum
from dataclasses import dataclass


class ErrorType(Enum):
    """Classification of errors for different handling strategies."""
    RETRYABLE = "retryable"      # Network timeouts, API rate limits
    FALLBACK = "fallback"        # Service unavailable, use alternative
    FATAL = "fatal"              # Invalid input, authentication failure
    HUMAN_REQUIRED = "human"     # Complex decision needed


@dataclass
class ErrorContext:
    """Context information for error handling."""
    node_name: str
    error: Exception
    state: Dict[str, Any]
    attempt: int
    max_attempts: int


class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt (exponential backoff)."""
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        return min(delay, self.max_delay)


def classify_error(error: Exception) -> ErrorType:
    """Classify error to determine handling strategy."""
    error_name = type(error).__name__
    error_msg = str(error).lower()
    
    # Retryable errors
    if any(keyword in error_msg for keyword in [
        "timeout", "rate limit", "connection", "temporary", "503", "502", "429"
    ]):
        return ErrorType.RETRYABLE
    
    # Fallback errors (service unavailable)
    if any(keyword in error_msg for keyword in [
        "service unavailable", "not found", "404", "500"
    ]):
        return ErrorType.FALLBACK
    
    # Fatal errors
    if any(keyword in error_msg for keyword in [
        "authentication", "unauthorized", "forbidden", "401", "403", "invalid"
    ]):
        return ErrorType.FATAL
    
    # Default to retryable for unknown errors
    return ErrorType.RETRYABLE


def with_error_handling(
    retry_config: Optional[RetryConfig] = None,
    fallback_func: Optional[Callable] = None,
    error_logger: Optional[logging.Logger] = None
):
    """
    Decorator for LangGraph nodes to add error handling.
    
    Args:
        retry_config: Retry configuration
        fallback_func: Function to call if main function fails
        error_logger: Logger for error reporting
    """
    if retry_config is None:
        retry_config = RetryConfig()
    
    if error_logger is None:
        error_logger = logging.getLogger(__name__)
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            node_name = func.__name__
            
            for attempt in range(1, retry_config.max_attempts + 1):
                try:
                    # Execute the main function
                    result = await func(state)
                    
                    # Success - return result
                    if attempt > 1:
                        error_logger.info(f"✅ {node_name} succeeded on attempt {attempt}")
                    
                    return result
                
                except Exception as error:
                    error_type = classify_error(error)
                    error_context = ErrorContext(
                        node_name=node_name,
                        error=error,
                        state=state,
                        attempt=attempt,
                        max_attempts=retry_config.max_attempts
                    )
                    
                    error_logger.warning(
                        f"❌ {node_name} failed (attempt {attempt}/{retry_config.max_attempts}): "
                        f"{type(error).__name__}: {error}"
                    )
                    
                    # Handle based on error type
                    if error_type == ErrorType.FATAL:
                        error_logger.error(f"💀 Fatal error in {node_name}: {error}")
                        return await _handle_fatal_error(error_context, fallback_func)
                    
                    elif error_type == ErrorType.HUMAN_REQUIRED:
                        error_logger.info(f"👤 Human intervention required in {node_name}")
                        return await _handle_human_required(error_context)
                    
                    elif error_type == ErrorType.FALLBACK and fallback_func:
                        error_logger.info(f"🔄 Using fallback for {node_name}")
                        try:
                            return await fallback_func(state)
                        except Exception as fallback_error:
                            error_logger.error(f"Fallback also failed: {fallback_error}")
                            # Continue to retry logic
                    
                    # Retryable error or fallback failed
                    if attempt < retry_config.max_attempts:
                        delay = retry_config.get_delay(attempt)
                        error_logger.info(f"⏳ Retrying {node_name} in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        # Max attempts reached
                        error_logger.error(f"💥 {node_name} failed after {retry_config.max_attempts} attempts")
                        return await _handle_max_attempts_reached(error_context, fallback_func)
            
            # Should never reach here
            return {"error": f"Unexpected error in {node_name}"}
        
        return wrapper
    return decorator


async def _handle_fatal_error(
    context: ErrorContext, 
    fallback_func: Optional[Callable]
) -> Dict[str, Any]:
    """Handle fatal errors that shouldn't be retried."""
    if fallback_func:
        try:
            return await fallback_func(context.state)
        except Exception as e:
            pass
    
    return {
        "error": f"Fatal error in {context.node_name}: {context.error}",
        "requires_human": True,
        "error_type": "fatal"
    }


async def _handle_human_required(context: ErrorContext) -> Dict[str, Any]:
    """Handle errors that require human intervention."""
    return {
        "error": f"Human intervention required in {context.node_name}: {context.error}",
        "requires_human": True,
        "error_type": "human_required",
        "context": {
            "node": context.node_name,
            "attempt": context.attempt,
            "state_keys": list(context.state.keys())
        }
    }


async def _handle_max_attempts_reached(
    context: ErrorContext,
    fallback_func: Optional[Callable]
) -> Dict[str, Any]:
    """Handle case when max retry attempts are reached."""
    if fallback_func:
        try:
            return await fallback_func(context.state)
        except Exception:
            pass
    
    return {
        "error": f"Max attempts reached for {context.node_name}: {context.error}",
        "requires_human": True,
        "error_type": "max_attempts",
        "attempts": context.max_attempts
    }


# Convenience functions for common fallback strategies

async def fallback_to_knowledge_base(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback: Use knowledge base instead of web search."""
    return {
        "search_results": [],
        "fallback_used": "knowledge_base",
        "message": "Web search failed, using knowledge base only"
    }


async def fallback_skip_step(state: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback: Skip the current step and continue."""
    return {
        "skipped": True,
        "message": "Step skipped due to error"
    }