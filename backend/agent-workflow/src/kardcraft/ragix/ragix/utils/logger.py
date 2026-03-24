import logging
import os
import structlog

ENV_MODE = os.getenv("ENV_MODE", "LOCAL").upper()

# Set default logging level based on environment
# Production should be INFO (less verbose), local/staging can be DEBUG
default_level = "INFO" if ENV_MODE == "PRODUCTION" else "DEBUG"
LOGGING_LEVEL = logging.getLevelNamesMapping().get(
    os.getenv("LOGGING_LEVEL", default_level).upper(),
    logging.INFO,
)

# Set root logger level (but don't add default handler - we'll add our own)
logging.getLogger().setLevel(LOGGING_LEVEL)
# Clear any existing handlers to avoid duplicate output
logging.getLogger().handlers.clear()

# Keep third-party library noise down (only warnings+)
NOISY_LOGGERS = (
    # AWS SDK
    "boto3", "botocore", "urllib3", "s3transfer", "watchtower",
    # HTTP clients
    "httpcore", "httpx", "aiohttp", "requests", "hpack",
    # Async / event loop
    "asyncio", "concurrent",
    # AI SDKs
    "openai", "anthropic", "httpx._client",
    # Web frameworks
    "uvicorn.access", "uvicorn.error", "fastapi",
    # Database
    "sqlalchemy", "databases", "aiosqlite",
    # Other
    "websockets", "multipart", "charset_normalizer",
)
for noisy_logger in NOISY_LOGGERS:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# Common pre-chain used by both console and CloudWatch formatters
# Simplified: only func_name for cleaner output (filename:lineno adds clutter)
foreign_pre_chain = [
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.CallsiteParameterAdder(
        {
            structlog.processors.CallsiteParameter.FILENAME,
            structlog.processors.CallsiteParameter.FUNC_NAME,
            structlog.processors.CallsiteParameter.LINENO,
        }
    ),
    structlog.contextvars.merge_contextvars,
]

# Renderer selection per environment
if ENV_MODE in ("LOCAL", "STAGING"):
    console_renderer = structlog.dev.ConsoleRenderer(colors=True)
else:
    console_renderer = structlog.processors.JSONRenderer()

# Configure structlog to emit into stdlib logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Console handler (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(LOGGING_LEVEL)
console_handler.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=console_renderer,
        foreign_pre_chain=foreign_pre_chain,
    )
)
logging.getLogger().addHandler(console_handler)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


from pathlib import Path
from datetime import datetime
from typing import Optional, Any
import time

class FileDebugLogger:
    _instance = None
    _files: dict = {}
    _start_times: dict = {}
    _debug_dir: Path = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._files = {}
            cls._instance._start_times = {}
            cls._instance._debug_dir = Path(__file__).parent.parent.parent / "debug_logs"
        return cls._instance
    
    def _get_file(self, session: str, category: str):
        key = f"{session}:{category}"
        
        if key not in self._files:
            self._debug_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{category}_{session[:8]}_{timestamp}.log" if session else f"{category}_{timestamp}.log"
            filepath = self._debug_dir / filename
            
            self._files[key] = open(filepath, 'a', encoding='utf-8')
            self._start_times[key] = time.perf_counter()
            
            self._files[key].write(f"# Debug Log: {category}\n")
            self._files[key].write(f"# Session: {session or 'default'}\n")
            self._files[key].write(f"# Started: {datetime.now().isoformat()}\n")
            self._files[key].write(f"# {'=' * 60}\n\n")
            self._files[key].flush()
        
        return self._files[key], self._start_times[key]
    
    def log(
        self,
        message: str,
        session: str = "default",
        category: str = "debug",
        save_to_file: bool = True,
        **kwargs
    ):
        if not save_to_file:
            return
        
        try:
            file, start_time = self._get_file(session, category)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            extras = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
            extras_str = f" | {extras}" if extras else ""
            
            line = f"[{elapsed_ms:10.1f}ms] {message}{extras_str}\n"
            file.write(line)
            file.flush()
        except Exception as e:
            pass
    
    def close(self, session: Optional[str] = None, category: Optional[str] = None):
        if session and category:
            key = f"{session}:{category}"
            if key in self._files:
                try:
                    self._files[key].close()
                except:
                    pass
                del self._files[key]
                if key in self._start_times:
                    del self._start_times[key]
        else:
            for f in self._files.values():
                try:
                    f.close()
                except:
                    pass
            self._files.clear()
            self._start_times.clear()
    
    def close_session(self, session: str):
        keys_to_remove = [k for k in self._files.keys() if k.startswith(f"{session}:")]
        for key in keys_to_remove:
            try:
                self._files[key].close()
            except:
                pass
            del self._files[key]
            if key in self._start_times:
                del self._start_times[key]


file_debug = FileDebugLogger()
